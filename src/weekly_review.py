#!/usr/bin/env python3
"""
CRYPTO RADAR - REVISÃO SEMANAL DO LIVE (Telegram)

Roda 1x/semana via cron (segunda de manhã) e manda um resumo no Telegram:
    - saldo total da conta e variação desde a revisão anterior;
    - trades fechados nos últimos 7 dias (acerto, P&L, saídas) e o total
      acumulado, com o progresso até 100 trades (ponto de reavaliar regras);
    - proteções que dispararam na semana (pausas, limite diário, circuit
      breaker, meta da carteira) e erros/avisos no log;
    - vendas do mês em R$ contra o limite de isenção de IR;
    - mercado (cesta de moedas com histórico completo no scanner): variação
      da semana, maiores altas/quedas, e se algum horário ou dia da semana
      repetiu a mesma direção por PATTERN_WEEKS semanas seguidas.

Só leitura: saldo pela API (fetch_balance), CSVs/log do live e o banco do
scanner. Não envia ordem nenhuma. Guarda o saldo de cada revisão em
data/weekly_review_state.json pra comparar com a próxima.

Uso:
  python3 src/weekly_review.py            # envia no Telegram
  python3 src/weekly_review.py --print    # só mostra na tela
"""

from __future__ import annotations

import csv
import json
import math
import re
import sqlite3
import statistics as st
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from binance_live_executor import ENV_FILE, build_exchange, load_env  # noqa: E402
from binance_live_trader import NEVER_BUY  # noqa: E402
from telegram_notify import send_telegram  # noqa: E402

DATA = ROOT / "data"
LEDGER = DATA / "binance_live_trades.csv"
OPEN_FILE = DATA / "binance_live_open_positions.csv"
DUST_LOG = DATA / "binance_live_dust_sweep.csv"
LIVE_LOG = DATA / "binance_live.log"
CONFIG = DATA / "binance_live_config.json"
SCANNER_DB = DATA / "crypto_radar.db"
STATE = DATA / "weekly_review_state.json"
REVIEW_LOG = DATA / "weekly_review.log"

BRT = ZoneInfo("America/Sao_Paulo")
REVIEW_AT_TRADES = 100
PATTERN_WEEKS = 6          # semanas seguidas na mesma direção pra chamar de padrão
MARKET_WEEKS = 10          # quantas semanas de histórico do scanner olhar
MONTHLY_EXEMPT_BRL = 35000.0
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
# Início do teste "sem compra 14h-18h Brasília" (NO_BUY_HOURS_BRT no trader).
NO_BUY_TEST_START = datetime(2026, 9, 25, 22, 0, tzinfo=timezone.utc)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def dt(iso: str) -> datetime | None:
    try:
        t = datetime.fromisoformat(iso.strip())
    except (ValueError, AttributeError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def usd(v: float, signed: bool = False) -> str:
    sign = ("+" if v >= 0 else "-") if signed else ("-" if v < 0 else "")
    return f"{sign}${abs(v):.2f}"


def account_value() -> tuple[float | None, str]:
    """Valor total da conta em USDT (saldo real pela API, só leitura)."""
    try:
        ex = build_exchange(load_env(ENV_FILE))
        ex.load_markets()
        bal = ex.fetch_balance()
        total = 0.0
        for asset, qty in bal.get("total", {}).items():
            if not qty:
                continue
            if asset == "USDT":
                total += qty
            elif f"{asset}/USDT" in ex.markets:
                total += qty * float(ex.fetch_ticker(f"{asset}/USDT")["last"])
        return total, ""
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def usdt_brl() -> float | None:
    try:
        with urllib.request.urlopen(
            "https://api.binance.com/api/v3/ticker/price?symbol=USDTBRL", timeout=10
        ) as resp:
            return float(json.loads(resp.read())["price"])
    except Exception:
        return None


def trades_section(now: datetime) -> list[str]:
    rows = read_csv(LEDGER)
    week = [r for r in rows if (dt(r["exit_time"]) or now) >= now - timedelta(days=7)]
    lines = []
    total_pnl = sum(float(r["pnl_usdt"]) for r in rows)
    if week:
        pnl = [float(r["pnl_usdt"]) for r in week]
        wins = sum(p > 0 for p in pnl)
        reasons = defaultdict(int)
        for r in week:
            reasons[r["exit_reason"]] += 1
        lines.append(
            f"Trades na semana: {len(week)} | acerto {wins / len(week):.0%} | "
            f"P&L {usd(sum(pnl), True)} | média {sum(float(r['gross_return_pct']) for r in week) / len(week):+.2f}%/trade"
        )
        lines.append("Saídas: " + ", ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])))
    else:
        lines.append("Trades na semana: nenhum")
    wins_all = sum(float(r["pnl_usdt"]) > 0 for r in rows)
    lines.append(
        f"Acumulado: {len(rows)} trades | acerto {wins_all / max(1, len(rows)):.0%} | P&L {usd(total_pnl, True)}"
        + (f" | faltam {REVIEW_AT_TRADES - len(rows)} pra 100 (reavaliar regras)"
           if len(rows) < REVIEW_AT_TRADES else " | passou de 100: hora de reavaliar as regras")
    )
    lines += no_buy_test_lines(rows)
    return lines


def no_buy_test_lines(rows: list[dict]) -> list[str]:
    """Compara trades abertos antes e depois do bloqueio de 14h-18h."""
    def stats(sel: list[dict]) -> str:
        if not sel:
            return "nenhum"
        rets = [float(r["gross_return_pct"]) for r in sel]
        return (f"{len(sel)} trades, média {sum(rets) / len(rets):+.2f}%, "
                f"acerto {sum(float(r['pnl_usdt']) > 0 for r in sel) / len(sel):.0%}")
    before = [r for r in rows if (dt(r["entry_time"]) or NO_BUY_TEST_START) < NO_BUY_TEST_START]
    after = [r for r in rows if (dt(r["entry_time"]) or NO_BUY_TEST_START) >= NO_BUY_TEST_START]
    in_window = [r for r in after if 14 <= dt(r["entry_time"]).astimezone(BRT).hour <= 18]
    lines = [f"Teste sem compra 14h-18h: antes {stats(before)} | depois {stats(after)}"]
    if in_window:
        lines.append(f"ATENÇÃO: {len(in_window)} compra(s) 14h-18h depois do bloqueio - conferir")
    return lines


def protections_section(now: datetime) -> list[str]:
    since = now - timedelta(days=7)
    counts = defaultdict(int)
    patterns = {
        "pausa por stops em série": "compras pausadas até",
        "limite de perda diária": "Limite de perda diária atingido",
        "meta da carteira": "Carteira bateu meta",
        "circuit breaker": "CIRCUIT BREAKER ATIVO: pulando",
        "compra pulada (+3% desde o sinal)": "pulado - preço",
        "dias com bloqueio 14h-18h": "Horário sem compra",
        "venda bloqueada/falhou": "venda de fechamento falhou",
        "ordem com estado incerto": "estado incerto",
        "erro no ciclo": "ERRO no ciclo",
    }
    if LIVE_LOG.exists():
        with LIVE_LOG.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = re.match(r"\[([^\]]+)\]", line)
                t = dt(m.group(1)) if m else None
                if t is None or t < since:
                    continue
                for label, needle in patterns.items():
                    if needle in line:
                        counts[label] += 1
    if not counts:
        return ["Proteções/avisos na semana: nenhum disparo"]
    return ["Proteções/avisos na semana: " + ", ".join(f"{k} {v}x" for k, v in counts.items())]


def month_sales_section(now: datetime, rate: float | None) -> list[str]:
    local = now.astimezone(BRT)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = 0.0
    for r in read_csv(LEDGER):
        t = dt(r["exit_time"])
        if t and t >= start:
            total += float(r["exit_price"]) * float(r["quantity"])
    for d in read_csv(DUST_LOG):
        t = dt(d.get("timestamp", ""))
        if t and t >= start and d.get("action") == "sell_usdt":
            total += float(d.get("value_usdt_est") or 0)
    if rate is None:
        return [f"Vendas no mês: {usd(total)} (cotação em R$ indisponível)"]
    brl = total * rate
    return [f"Vendas no mês: R$ {brl:,.0f} = {brl / MONTHLY_EXEMPT_BRL:.0%} do limite de isenção de IR (R$ 35 mil)".replace(",", ".")]


def market_section(now: datetime) -> list[str]:
    con = sqlite3.connect(SCANNER_DB)
    start = now - timedelta(weeks=MARKET_WEEKS)
    px: dict[str, dict[int, float]] = defaultdict(dict)
    for ts, sym, p in con.execute(
        "select timestamp, symbol, price from scanner_v3_results where timeframe='1h' and timestamp >= ?",
        (start.isoformat(),),
    ):
        t = dt(ts)
        if t:
            px[sym.split("/")[0]][int(t.timestamp() // 3600)] = float(p)
    con.close()
    h_now = int(now.timestamp() // 3600)
    h_week = h_now - 7 * 24
    lines = []

    # moedas: variação na semana (só quem tem preço no começo e no fim)
    moves = []
    for s, ser in px.items():
        if s in NEVER_BUY:
            continue
        a = next((ser[h] for h in range(h_week, h_week + 6) if h in ser), None)
        b = next((ser[h] for h in range(h_now, h_now - 6, -1) if h in ser), None)
        if a and b:
            moves.append((s, (b / a - 1) * 100))
    if moves:
        moves.sort(key=lambda x: -x[1])
        med = st.median(m for _, m in moves)
        btc = next((m for s, m in moves if s == "BTC"), None)
        lines.append(
            f"Mercado na semana ({len(moves)} moedas): mediana {med:+.1f}%"
            + (f", BTC {btc:+.1f}%" if btc is not None else "")
        )
        lines.append("Altas: " + ", ".join(f"{s} {m:+.0f}%" for s, m in moves[:5]))
        lines.append("Quedas: " + ", ".join(f"{s} {m:+.0f}%" for s, m in moves[-5:]))

    # cesta: moedas com preço em >= 80% das horas do período
    span = h_now - int(start.timestamp() // 3600)
    basket = [s for s, ser in px.items() if s not in NEVER_BUY and len(ser) >= 0.8 * span]
    mk: dict[int, float] = {}
    for h in range(h_now - span, h_now):
        v = [math.log(px[s][h + 1] / px[s][h]) * 100 for s in basket if h in px[s] and h + 1 in px[s]]
        if len(v) >= max(5, len(basket) // 2):
            mk[h] = st.mean(v)
    if not mk:
        return lines

    def week_of(h: int) -> int:
        return (h_now - 1 - h) // (7 * 24)   # 0 = semana mais recente

    def local(h: int) -> datetime:
        return datetime.fromtimestamp(h * 3600, BRT)

    def streak(values_by_week: dict[int, float]) -> int:
        """Semanas seguidas (a partir da mais recente) com o mesmo sinal."""
        n, sign = 0, 0
        for w in range(MARKET_WEEKS):
            v = values_by_week.get(w)
            if v is None or v == 0:
                break
            s = 1 if v > 0 else -1
            if sign == 0:
                sign = s
            if s != sign:
                break
            n += 1
        return n * sign

    found = []
    for hb in range(0, 24, 3):
        by_w = defaultdict(float)
        for h, v in mk.items():
            if hb <= local(h).hour < hb + 3:
                by_w[week_of(h)] += v
        s = streak(by_w)
        if abs(s) >= PATTERN_WEEKS:
            found.append(f"{hb:02d}-{hb + 2:02d}h {'sobe' if s > 0 else 'cai'} há {abs(s)} semanas")
    for d in range(7):
        by_w = defaultdict(float)
        for h, v in mk.items():
            if local(h).weekday() == d:
                by_w[week_of(h)] += v
        s = streak(by_w)
        if abs(s) >= PATTERN_WEEKS:
            found.append(f"{DIAS[d]} {'sobe' if s > 0 else 'cai'} há {abs(s)} semanas")
    weeks_avail = (max(week_of(h) for h in mk) + 1) if mk else 0
    if found:
        lines.append("PADRÃO (mesma direção por %d+ semanas): " % PATTERN_WEEKS + "; ".join(found))
    else:
        lines.append(
            f"Horário/dia da semana: nenhum padrão por {PATTERN_WEEKS}+ semanas seguidas "
            f"({weeks_avail} semanas de histórico, cesta de {len(basket)} moedas)"
        )
    return lines


def main() -> int:
    only_print = "--print" in sys.argv
    now = datetime.now(timezone.utc)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}

    total, err = account_value()
    cfg = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    base = float(cfg.get("baseline_capital_usdt") or 0)
    lines = [f"[LIVE] Revisão semanal - {now.astimezone(BRT):%d/%m/%Y %H:%M}"]
    if total is not None:
        prev = state.get("total_usdt")
        lines.append(
            f"Conta: {usd(total)}"
            + (f" ({usd(total - prev, True)} desde {state.get('date', '?')})" if prev else "")
            + (f" | capital-base {usd(base)}" if base else "")
        )
    else:
        lines.append(f"Conta: não consegui ler o saldo ({err})")
    lines += trades_section(now)
    lines += protections_section(now)
    lines += month_sales_section(now, usdt_brl())
    try:
        lines += market_section(now)
    except Exception as exc:
        lines.append(f"Mercado: erro na análise ({type(exc).__name__}: {exc})")

    text = "\n".join(lines)
    print(text)
    if only_print:
        return 0

    ok = send_telegram(text[:4000])
    with REVIEW_LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"[{now.isoformat()}] enviado={ok}\n{text}\n{'-' * 60}\n")
    if total is not None:
        STATE.write_text(
            json.dumps({"date": now.astimezone(BRT).strftime("%d/%m"), "total_usdt": total}),
            encoding="utf-8",
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
