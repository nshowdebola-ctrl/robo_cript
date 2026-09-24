#!/usr/bin/env python3
"""
CRYPTO RADAR - BINANCE LIVE TRADER (mainnet, DINHEIRO REAL)

Paralelo de binance_testnet_trader.py, apontado pro Binance Spot
MAINNET. Liga os sinais LONG reais do scanner_v3 (via
forward_signals.csv, só leitura) a ordens reais - compra/monitora/
vende com dinheiro de verdade.

FASE 3 do roteiro (ver memória do projeto): esta é a engenharia que
pode ser adiantada sem chave real. `main()` e `binance_live_loop.py`
tentam `load_env(ENV_FILE)` ANTES de qualquer chamada ccxt - sem
`.binance-live.env` (não criado nesta fase), falha limpo com
`FileNotFoundError` e retorna 1, sem jamais construir o exchange nem
tocar a rede. Esse é o mecanismo concreto que garante "sem chave, sem
ordem real" enquanto esta fase durar.

Isolado do paper trading v9 e do testnet de propósito:
    - Lê forward_signals.csv (só leitura).
    - Mantém posição/ledger PRÓPRIOS
      (data/binance_live_open_positions.csv, data/binance_live_trades.csv)
      - não compartilha estado com v9_17/v9_18/v9_21 nem com o testnet.
    - STOP_PCT/TARGET_PCT/MAX_HOLD_HOURS importados de
      paper_trading_v9_17.py (mesma fonte única que o testnet usa -
      nunca duplicar, já causou divergência real neste projeto).
    - Circuit breaker de drawdown (binance_live_circuit_breaker.py):
      antes de abrir posição nova, verifica se a perda acumulada desde
      um capital-base configurável passou do limite. Se sim, pula a
      abertura neste e nos próximos ciclos até reativação manual -
      posições já abertas continuam saindo normalmente por
      STOP/TARGET/TIME.

Sem cron - rodar manualmente ou via binance_live_loop.py:
    python3 src/binance_live_trader.py

Valor por posição / capital-base / limite de drawdown lidos de
data/binance_live_config.json a cada ciclo (não precisa reiniciar nada
pra mudar) - o portal (web/live.php) escreve esse arquivo.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ccxt

from binance_live_executor import (
    ENV_FILE,
    LOG_FILE,
    build_exchange,
    OrderStateUnknown,
    _find_order_by_client_id,
    call_with_retry,
    load_env,
    log,
    place_market_order,
)
from binance_live_circuit_breaker import check_and_maybe_trip
from binance_testnet_trader import (
    append_csv,
    best_actionable_per_symbol,
    read_csv,
    write_csv,
)
from paper_trading_v9_17 import MAX_HOLD_HOURS, STOP_PCT, TARGET_PCT
from paper_trading_v9_21 import SIGNALS, parse_dt
from telegram_notify import send_telegram

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

LIVE_OPEN_FILE = DATA / "binance_live_open_positions.csv"
LIVE_LEDGER = DATA / "binance_live_trades.csv"

LIVE_OPEN_FIELDS = [
    "signal_id", "symbol", "entry_time", "entry_price", "quantity",
    "entry_cost_usdt", "buy_order_id", "score", "confidence",
    "target_reached",
]
LIVE_LEDGER_FIELDS = [
    "trade_id", "symbol", "entry_time", "exit_time", "entry_price",
    "exit_price", "quantity", "exit_reason", "gross_return_pct",
    "pnl_usdt", "buy_order_id", "sell_order_id",
]

LIVE_CONFIG_FILE = DATA / "binance_live_config.json"

MAX_POSITIONS_LIVE = 8
PORTFOLIO_TARGET_PCT = 0.04          # soma do P&L não realizado de todas as posições abertas >= 4% do custo de entrada delas -> fecha tudo
LIVE_NOTIONAL_USDT = 10.0            # default, usado se config.json faltar/for inválido
BASELINE_CAPITAL_USDT = 500.0        # placeholder - ajustar conscientemente antes da Fase 4
MAX_DRAWDOWN_PCT = 10.0              # placeholder - ajustar conscientemente antes da Fase 4

# Reserva mínima de BNB livre pra pagar taxa (a opção "pagar taxa com BNB"
# está ligada na conta). Sem BNB livre a Binance cobra a taxa no próprio
# ativo comprado, o saldo líquido fica ~0,1% menor que o registrado e a
# venda deixa resto na carteira. Cada trade gasta ~0.0000065 BNB.
BNB_RESERVE_MIN = 0.002

# Piso de $6, não $5: a Binance recusa ordem abaixo de $5 (inclusive a
# mercado). Uma posição de $5 que cai 5% no STOP vale $4,75 e a venda de
# saída seria recusada, prendendo a posição. Com $6 o STOP sai a $5,70.
NOTIONAL_BOUNDS = (6.0, 100.0)
BASELINE_CAPITAL_BOUNDS = (10.0, 1_000_000.0)
MAX_DRAWDOWN_BOUNDS = (2.0, 50.0)

# Pausa após queda do mercado: 2+ STOPs com até 15min entre eles ->
# nenhuma compra nova por 90min contados do último STOP. Em 23/09
# 4 STOPs saíram entre 14:10 e 14:17 e o robô recomprou LTC/AVAX/ADA
# no mesmo minuto, no meio da queda.
STOP_CLUSTER_MIN = 2
STOP_CLUSTER_WINDOW = timedelta(minutes=15)
STOP_CLUSTER_PAUSE = timedelta(minutes=90)

# Pausa por moeda: não recompra um símbolo fechado (por qualquer motivo)
# há menos de 4h. Em 23/09 ZRO bateu TARGET, foi recomprado na hora e
# saiu por STOP 1h depois.
SYMBOL_COOLDOWN = timedelta(hours=4)


def _clamped(value, bounds, default):
    lo, hi = bounds
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if lo <= v <= hi:
        return v
    return default


def load_live_config() -> dict:
    defaults = {
        "notional_usdt": LIVE_NOTIONAL_USDT,
        "baseline_capital_usdt": BASELINE_CAPITAL_USDT,
        "max_drawdown_pct": MAX_DRAWDOWN_PCT,
    }
    try:
        raw = json.loads(LIVE_CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return defaults
    return {
        "notional_usdt": _clamped(raw.get("notional_usdt"), NOTIONAL_BOUNDS, defaults["notional_usdt"]),
        "baseline_capital_usdt": _clamped(
            raw.get("baseline_capital_usdt"), BASELINE_CAPITAL_BOUNDS, defaults["baseline_capital_usdt"]
        ),
        "max_drawdown_pct": _clamped(
            raw.get("max_drawdown_pct"), MAX_DRAWDOWN_BOUNDS, defaults["max_drawdown_pct"]
        ),
    }


def live_open_ids(open_rows: list[dict]) -> set[str]:
    return {r["signal_id"].strip() for r in open_rows if r.get("signal_id")}


def live_closed_ids(ledger_rows: list[dict]) -> set[str]:
    result = set()
    for r in ledger_rows:
        tid = r.get("trade_id", "").strip()
        if tid:
            result.add(tid.rsplit("_", 1)[0])
    return result


# signal_ids já alertados por venda bloqueada, pra não mandar Telegram
# a cada ciclo de 60s. Vive só no processo do loop - se reiniciar, avisa
# de novo uma vez, o que é aceitável.
_blocked_alerted: set[str] = set()


_unknown_alerted: set[str] = set()

# (tipo, chave) -> client id de ordem com destino incerto. No ciclo
# seguinte a checagem é retomada por esse id ANTES de qualquer novo
# envio; sem isso, um novo id reenviaria uma ordem que talvez já tenha
# sido executada. Só em memória: se o loop reiniciar, vale o alerta.
_pending_orders: dict[tuple[str, str], str] = {}


def _place_or_resume(exchange, kind: str, key: str, symbol: str, side: str, amount: float):
    pending_id = _pending_orders.get((kind, key))
    if pending_id:
        # Pode levantar OrderStateUnknown de novo - e o pendente continua.
        found = _find_order_by_client_id(exchange, symbol, pending_id)
        if found is not None:
            status = found.get("status")
            if status == "closed" and float(found.get("filled") or 0.0) > 0:
                _pending_orders.pop((kind, key), None)
                log(
                    f"[LIVE] {symbol}: ordem incerta do ciclo anterior estava "
                    f"executada (id {found.get('id')}) - usando, sem reenviar."
                )
                return found
            if status not in ("canceled", "expired", "rejected"):
                raise OrderStateUnknown(
                    f"ordem {pending_id} ({symbol}) com status {status!r} - "
                    "conferir na conta.",
                    client_id=pending_id,
                )
        _pending_orders.pop((kind, key), None)  # confirmado que não executou
    try:
        return place_market_order(exchange, symbol, side, amount)
    except OrderStateUnknown as exc:
        if exc.client_id:
            _pending_orders[(kind, key)] = exc.client_id
        raise


def _alert_order_state_unknown(
    kind: str, symbol: str, key: str, exc: Exception
) -> None:
    """Ordem com destino incerto: nunca reenviar sozinho. Alerta uma vez
    por posição/sinal e deixa a conferência pra você na conta."""
    log(f"[LIVE] ALERTA: {kind} de {symbol} com estado incerto - {exc}")
    if key not in _unknown_alerted:
        _unknown_alerted.add(key)
        send_telegram(
            f"[LIVE] ATENÇÃO: não sei se a {kind} de {symbol} foi executada "
            "(erro de rede ao confirmar). Não vou reenviar - confira a conta "
            "na Binance e o CSV de posições."
        )


_bnb_reserve_alerted = False
_low_usdt_logged = False
# Fim da pausa por STOPs em série já avisada (log/Telegram uma vez por pausa).
_stop_cluster_alerted_until: datetime | None = None


def stop_cluster_pause_until(
    ledger_rows: list[dict], now: datetime
) -> datetime | None:
    """Se houve STOP_CLUSTER_MIN+ STOPs com no máximo STOP_CLUSTER_WINDOW
    entre o primeiro e o último, devolve até quando as compras ficam
    pausadas (último STOP do grupo + STOP_CLUSTER_PAUSE), se ainda for
    no futuro. Lido do ledger: sobrevive a reinício do loop."""
    horizon = now - STOP_CLUSTER_PAUSE - STOP_CLUSTER_WINDOW
    stops = sorted(
        t for t in (
            parse_dt(r["exit_time"]) for r in ledger_rows
            if (r.get("exit_reason") or "").strip() == "STOP"
        )
        if t is not None and t >= horizon
    )
    pause_until = None
    for i in range(STOP_CLUSTER_MIN - 1, len(stops)):
        if stops[i] - stops[i - STOP_CLUSTER_MIN + 1] <= STOP_CLUSTER_WINDOW:
            pause_until = stops[i] + STOP_CLUSTER_PAUSE
    if pause_until and pause_until > now:
        return pause_until
    return None


def symbols_in_cooldown(ledger_rows: list[dict], now: datetime) -> set[str]:
    """Símbolos fechados há menos de SYMBOL_COOLDOWN."""
    cooling = set()
    for r in ledger_rows:
        closed_at = parse_dt(r.get("exit_time") or "")
        if closed_at is not None and now - closed_at < SYMBOL_COOLDOWN:
            cooling.add(r["symbol"].strip().upper())
    return cooling


def check_bnb_reserve(exchange, open_positions: list[dict]) -> None:
    """Avisa (uma vez, até recuperar) se a reserva de BNB livre está
    abaixo de BNB_RESERVE_MIN. Nunca levanta exceção: é só um aviso e
    não pode derrubar o ciclo."""
    global _bnb_reserve_alerted
    try:
        balance = call_with_retry(exchange.fetch_balance)
    except Exception as exc:
        log(f"AVISO reserva de BNB: falha ao consultar saldo ({type(exc).__name__}: {exc})")
        return

    free = balance.get("BNB", {}).get("free", 0.0) or 0.0
    # O BNB de uma posição aberta é da posição (vai ser vendido), não conta
    # como reserva de taxa.
    in_position = sum(
        float(p.get("quantity") or 0.0)
        for p in open_positions
        if (p.get("symbol") or "").strip().upper() == "BNB/USDT"
    )
    reserve = free - in_position
    if reserve >= BNB_RESERVE_MIN:
        _bnb_reserve_alerted = False
        return

    earn = balance.get("LDBNB", {}).get("total", 0.0) or 0.0
    where = (
        f" Há {earn:g} BNB no Simple Earn (LDBNB) - resgate pra Spot e "
        "confira se a assinatura automática do BNB está desligada."
        if earn > 0 else ""
    )
    log(
        f"AVISO: reserva de BNB livre baixa ({reserve:.6f} < {BNB_RESERVE_MIN}) "
        "- a taxa passa a ser cobrada no próprio ativo e as vendas deixam "
        f"resto na carteira.{where}"
    )
    if not _bnb_reserve_alerted:
        _bnb_reserve_alerted = True
        send_telegram(
            f"[LIVE] ATENÇÃO: reserva de BNB livre baixa ({reserve:.6f} BNB, "
            f"mínimo {BNB_RESERVE_MIN}). Sem BNB a taxa é cobrada no ativo "
            f"e as vendas deixam resto.{where}"
        )


def _warn_sell_blocked(
    pos: dict, symbol: str, base: str, reason: str, balance: dict
) -> None:
    """Posição bateu STOP/TARGET/TIME mas não há saldo livre pra vender.

    Caso conhecido: a Binance move o ativo parado da Spot pro Simple
    Earn (assinatura automática), e ele passa a aparecer como LD<ativo>
    - fora do alcance da ordem de venda spot."""
    earn = balance.get(f"LD{base}", {}).get("total", 0.0) or 0.0
    if earn > 0:
        where = (
            f"O saldo está no Simple Earn (LD{base}={earn:g}) - resgate "
            "pra Spot no app e o loop vende sozinho."
        )
    else:
        where = "Não achei saldo em LD* também - investigar na conta."
    log(
        f"AVISO: {symbol} bateu {reason} mas saldo livre de {base} está "
        f"zerado - mantendo posição aberta. {where}"
    )
    signal_id = pos["signal_id"]
    if signal_id not in _blocked_alerted:
        _blocked_alerted.add(signal_id)
        send_telegram(
            f"[LIVE] ATENÇÃO: {symbol} bateu {reason} mas não consigo "
            f"vender (saldo livre de {base} zerado). {where}"
        )


def _drop_already_closed(positions: list[dict]) -> list[dict]:
    """Tira do CSV de abertas o que o ledger já registra como fechado.

    Cobre a janela entre gravar o fechamento no ledger e reescrever o
    CSV (crash no meio, ou o incidente do ARB): sem isso a posição
    fantasma seria vendida de novo - e uma sobra de saldo viraria uma
    segunda linha no ledger."""
    closed_ids = live_closed_ids(read_csv(LIVE_LEDGER))
    kept = []
    for pos in positions:
        if (pos.get("signal_id") or "").strip() in closed_ids:
            log(
                f"[LIVE] {pos.get('symbol')}: já consta como fechada no "
                "ledger - removendo do CSV de abertas sem vender de novo."
            )
        else:
            kept.append(pos)
    return kept


def monitor_open_positions(exchange) -> tuple[list[dict], int]:
    remaining = []
    closed_now = 0
    balance = None
    positions = read_csv(LIVE_OPEN_FILE)
    reconciled = _drop_already_closed(positions)
    if len(reconciled) != len(positions):
        write_csv(LIVE_OPEN_FILE, LIVE_OPEN_FIELDS, reconciled)
    positions = reconciled

    # Uma passada só pra cotar tudo de uma vez - reaproveitada pro
    # cálculo da carteira inteira e pro loop por posição abaixo (evita
    # bater a API duas vezes pro mesmo símbolo no mesmo ciclo).
    prices: dict[int, float] = {}
    total_entry_cost = 0.0
    total_current_value = 0.0
    priced_all = True
    for index, pos in enumerate(positions):
        symbol = pos["symbol"]
        try:
            ticker = call_with_retry(exchange.fetch_ticker, symbol)
            price = ticker["last"]
        except Exception as exc:
            log(f"AVISO monitor {symbol}: {type(exc).__name__}: {exc}")
            priced_all = False
            continue
        prices[index] = price
        total_entry_cost += float(pos.get("entry_cost_usdt") or 0.0)
        total_current_value += price * float(pos["quantity"])

    # Meta da carteira: soma do P&L não realizado de TODAS as posições
    # abertas >= PORTFOLIO_TARGET_PCT do que foi investido nelas. Só
    # decide com o preço de todas cotado (se uma falhou, tenta de novo
    # no próximo ciclo em vez de decidir com visão parcial).
    portfolio_triggered = False
    if priced_all and positions and total_entry_cost > 0:
        portfolio_pnl_pct = (total_current_value - total_entry_cost) / total_entry_cost
        if portfolio_pnl_pct >= PORTFOLIO_TARGET_PCT:
            portfolio_triggered = True
            log(
                f"[LIVE] Carteira bateu meta de {PORTFOLIO_TARGET_PCT:.0%} "
                f"({portfolio_pnl_pct:+.2%} sobre ${total_entry_cost:.2f} "
                "investido) - fechando todas as posições abertas."
            )

    for index, pos in enumerate(positions):
        symbol = pos["symbol"]
        if index not in prices:
            remaining.append(pos)
            continue
        price = prices[index]

        entry = float(pos["entry_price"])
        change = price / entry - 1.0
        opened = parse_dt(pos["entry_time"])
        age_hours = (datetime.now(timezone.utc) - opened).total_seconds() / 3600.0

        reason = None
        if change <= -STOP_PCT:
            reason = "STOP"
        elif change >= TARGET_PCT:
            reason = "TARGET"
        elif age_hours >= MAX_HOLD_HOURS:
            reason = "TIME"
        elif portfolio_triggered:
            reason = "PORTFOLIO_TARGET"

        if not reason:
            remaining.append(pos)
            continue

        base = symbol.split("/")[0]
        if balance is None:
            try:
                balance = call_with_retry(exchange.fetch_balance)
            except Exception as exc:
                log(
                    f"AVISO: falha ao consultar saldo pra fechar {symbol} "
                    f"({type(exc).__name__}: {exc}) - mantendo posição aberta "
                    "pra tentar de novo no próximo ciclo."
                )
                remaining.append(pos)
                continue

        free = balance.get(base, {}).get("free", 0.0) or 0.0
        tracked_qty = float(pos["quantity"])
        # Nunca vende mais do que o saldo livre real - a diferença pra
        # quantidade rastreada na compra normalmente vem da taxa de
        # negociação cobrada no próprio ativo (sem BNB pra pagar com
        # desconto), que reduz o saldo líquido recebido.
        sell_qty = min(tracked_qty, free)
        if sell_qty <= 0:
            _warn_sell_blocked(pos, symbol, base, reason, balance)
            remaining.append(pos)
            continue
        _blocked_alerted.discard(pos["signal_id"])

        try:
            quantity = float(exchange.amount_to_precision(symbol, sell_qty))
            if quantity <= 0:
                raise ValueError(
                    f"saldo {sell_qty} abaixo do lote mínimo de {symbol}"
                )
            sell_order = _place_or_resume(
                exchange, "sell", pos["signal_id"], symbol, "sell", quantity
            )
        except OrderStateUnknown as exc:
            _alert_order_state_unknown("venda", symbol, pos["signal_id"], exc)
            remaining.append(pos)
            continue
        except Exception as exc:
            log(
                f"AVISO: {symbol} bateu {reason} mas venda de fechamento "
                f"falhou ({type(exc).__name__}: {exc}) - mantendo posição "
                "aberta pra tentar de novo no próximo ciclo."
            )
            remaining.append(pos)
            continue

        fill_price = sell_order.get("average") or sell_order.get("price") or price
        gross_return_pct = (float(fill_price) / entry - 1.0) * 100.0
        exit_time = datetime.now(timezone.utc).isoformat()

        sold_qty = float(sell_order.get("filled") or quantity)
        entry_cost = (pos.get("entry_cost_usdt") or "").strip()
        entry_cost_usdt = float(entry_cost) if entry_cost else entry * tracked_qty
        exit_cost_usdt = float(
            sell_order.get("cost") or (float(fill_price) * sold_qty)
        )
        # O lote mínimo do par arredonda a venda pra baixo e deixa uma
        # sobra na carteira (ex.: BNB com passo 0.001). O custo dessa
        # sobra não pode ser cobrado do PnL da parte vendida - senão um
        # trade com +7% aparece como prejuízo. A perda de quantidade por
        # taxa no ativo, essa sim, continua contando (sell_qty já é o
        # que realmente sobrou dela).
        sold_fraction = min(1.0, sold_qty / sell_qty)
        pnl_usdt = exit_cost_usdt - entry_cost_usdt * sold_fraction
        if sold_fraction < 1.0:
            log(
                f"[LIVE] {symbol}: sobra de {sell_qty - sold_qty:.8f} {base} "
                "ficou na carteira (lote mínimo do par)."
            )

        append_csv(LIVE_LEDGER, LIVE_LEDGER_FIELDS, {
            "trade_id": f"{pos['signal_id']}_{exit_time}",
            "symbol": symbol,
            "entry_time": pos["entry_time"],
            "exit_time": exit_time,
            "entry_price": pos["entry_price"],
            "exit_price": f"{float(fill_price):.12f}",
            "quantity": f"{sold_qty:.12f}",
            "exit_reason": reason,
            "gross_return_pct": f"{gross_return_pct:.6f}",
            "pnl_usdt": f"{pnl_usdt:.6f}",
            "buy_order_id": pos.get("buy_order_id", ""),
            "sell_order_id": sell_order.get("id", ""),
        })
        log(
            f"[LIVE] CLOSE {symbol:12s} {reason:6s} "
            f"gross={gross_return_pct:+.4f}% pnl=${pnl_usdt:+.4f} "
            f"sell_order={sell_order.get('id')}"
        )
        send_telegram(
            f"[LIVE] {symbol} fechado por {reason}: "
            f"{gross_return_pct:+.2f}% (${pnl_usdt:+.2f} dinheiro real)"
        )
        closed_now += 1
        # Reescreve o CSV já agora, a cada fechamento: se algo falhar
        # mais adiante no ciclo, a posição vendida não volta a aparecer
        # como aberta no ciclo seguinte.
        write_csv(
            LIVE_OPEN_FILE, LIVE_OPEN_FIELDS, remaining + positions[index + 1:]
        )

    return remaining, closed_now


def open_new_positions(
    exchange, remaining: list[dict], notional_usdt: float
) -> list[dict]:
    global _low_usdt_logged, _stop_cluster_alerted_until
    slots = max(0, MAX_POSITIONS_LIVE - len(remaining))
    if slots <= 0:
        return remaining

    now = datetime.now(timezone.utc)
    ledger_rows = read_csv(LIVE_LEDGER)
    pause_until = stop_cluster_pause_until(ledger_rows, now)
    if pause_until is not None:
        if _stop_cluster_alerted_until != pause_until:
            _stop_cluster_alerted_until = pause_until
            msg = (
                f"[LIVE] {STOP_CLUSTER_MIN}+ STOPs em até "
                f"{int(STOP_CLUSTER_WINDOW.total_seconds() // 60)}min - compras "
                f"pausadas até {pause_until:%H:%M} UTC (posições abertas "
                "continuam saindo normalmente)."
            )
            log(msg)
            send_telegram(msg)
        return remaining

    # Só abre o que o USDT livre paga. Sem isso, com vaga sobrando e saldo
    # curto o loop tentaria comprar todo ciclo e falharia (log repetido).
    try:
        free_usdt = float(
            call_with_retry(exchange.fetch_balance).get("USDT", {}).get("free", 0.0)
            or 0.0
        )
    except Exception as exc:
        log(f"AVISO abertura: falha ao consultar USDT livre ({type(exc).__name__}: {exc}) - sem abrir posição neste ciclo.")
        return remaining
    affordable = int(free_usdt // notional_usdt)
    if affordable <= 0:
        if not _low_usdt_logged:
            _low_usdt_logged = True
            log(
                f"[LIVE] {slots} vaga(s) livre(s), mas USDT livre (${free_usdt:.2f}) "
                f"não cobre uma posição de ${notional_usdt:.2f} - aguardando saldo."
            )
        return remaining
    _low_usdt_logged = False
    slots = min(slots, affordable)

    open_rows = read_csv(LIVE_OPEN_FILE)
    open_ids = live_open_ids(open_rows)
    closed_ids = live_closed_ids(ledger_rows)
    open_symbols = {p["symbol"].strip().upper() for p in remaining}
    cooling = symbols_in_cooldown(ledger_rows, now)

    candidates = best_actionable_per_symbol(open_ids, closed_ids)

    for sym, signal in candidates.items():
        if slots <= 0:
            break
        if sym in open_symbols or sym.strip().upper() in cooling:
            continue

        try:
            ticker = call_with_retry(exchange.fetch_ticker, sym)
            price = ticker["last"]
            raw_amount = notional_usdt / price
            amount = float(exchange.amount_to_precision(sym, raw_amount))
            buy_order = _place_or_resume(
                exchange, "buy", signal["signal_id"], sym, "buy", amount
            )
        except ccxt.BadSymbol:
            continue
        except OrderStateUnknown as exc:
            _alert_order_state_unknown("compra", sym, signal["signal_id"], exc)
            break  # sem saber o que houve, não abre mais nada neste ciclo
        except Exception as exc:
            log(f"[LIVE] AVISO abertura {sym}: {type(exc).__name__}: {exc}")
            continue

        filled = float(buy_order.get("filled") or 0.0)
        if filled <= 0:
            log(f"[LIVE] AVISO {sym}: ordem de compra não preencheu, ignorando.")
            continue

        fill_price = buy_order.get("average") or buy_order.get("price") or price
        entry_cost_usdt = float(buy_order.get("cost") or (float(fill_price) * filled))
        entry_time = datetime.now(timezone.utc).isoformat()

        remaining.append({
            "signal_id": signal["signal_id"],
            "symbol": sym,
            "entry_time": entry_time,
            "entry_price": f"{float(fill_price):.12f}",
            "quantity": f"{filled:.12f}",
            "entry_cost_usdt": f"{entry_cost_usdt:.6f}",
            "buy_order_id": str(buy_order.get("id", "")),
            "score": signal.get("score", ""),
            "confidence": signal.get("confidence", ""),
            "target_reached": "0",
        })
        # Grava já a cada compra: se o ciclo falhar depois, o ativo
        # comprado não fica sem registro (e o mesmo sinal não é
        # recomprado no ciclo seguinte).
        write_csv(LIVE_OPEN_FILE, LIVE_OPEN_FIELDS, remaining)
        open_symbols.add(sym)
        slots -= 1
        log(
            f"[LIVE] OPEN  {sym:12s} entry={fill_price} qty={filled} "
            f"buy_order={buy_order.get('id')}"
        )

    return remaining


def run_cycle(exchange) -> tuple[int, int, bool]:
    """Um ciclo completo: monitora/fecha posições (sempre), checa o
    circuit breaker, e só abre posição nova se não estiver travado."""
    cfg = load_live_config()
    remaining, closed_now = monitor_open_positions(exchange)
    check_bnb_reserve(exchange, remaining)

    ledger_rows = read_csv(LIVE_LEDGER)
    cb_state = check_and_maybe_trip(
        ledger_rows, cfg["baseline_capital_usdt"], cfg["max_drawdown_pct"]
    )
    halted = bool(cb_state["tripped"])

    if not halted:
        remaining = open_new_positions(exchange, remaining, cfg["notional_usdt"])
    else:
        log("[LIVE] CIRCUIT BREAKER ATIVO: pulando abertura de novas posições neste ciclo.")

    write_csv(LIVE_OPEN_FILE, LIVE_OPEN_FIELDS, remaining)
    return closed_now, len(remaining), halted


def main() -> int:
    print("=" * 100)
    print("CRYPTO RADAR - BINANCE LIVE TRADER")
    print("=" * 100)
    print("AMBIENTE: BINANCE SPOT MAINNET - DINHEIRO REAL")
    print(f"Sinais: {SIGNALS}")
    print(f"STOP / TARGET / MAX_HOLD: {STOP_PCT:.2%} / {TARGET_PCT:.2%} / {MAX_HOLD_HOURS}h")
    cfg = load_live_config()
    print(
        f"Notional por posição: ${cfg['notional_usdt']:.2f} | "
        f"Máx. posições: {MAX_POSITIONS_LIVE} | "
        f"Capital-base: ${cfg['baseline_capital_usdt']:.2f} | "
        f"Limite drawdown: {cfg['max_drawdown_pct']:.1f}%"
    )
    print("-" * 100)

    try:
        env = load_env(ENV_FILE)
        exchange = build_exchange(env)
        exchange.load_markets()
    except Exception as exc:
        log(f"ERRO de configuração: {exc}")
        return 1

    closed_now, open_count, halted = run_cycle(exchange)

    log(
        f"[LIVE] CICLO concluído: {closed_now} fechada(s), "
        f"{open_count} posição(ões) aberta(s)."
        + (" CIRCUIT BREAKER ATIVO." if halted else "")
    )
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
