#!/usr/bin/env python3
"""
CRYPTO RADAR - CIRCUIT BREAKER DE DRAWDOWN (live trading, dinheiro real)

Trava a abertura de posições NOVAS no binance_live_trader.py se a
perda acumulada (soma de pnl_usdt no ledger, desde um capital-base
configurável) passar de um limite percentual - posições já abertas
continuam sendo monitoradas e saem normalmente por STOP/TARGET/TIME,
só a abertura de posição nova é bloqueada.

Fórmula (perda acumulada desde um capital-base fixo, não
peak-to-trough - decisão tomada com o usuário em 2026-09-05):
    cumulative_pnl_usdt = soma de pnl_usdt no ledger com
        exit_time > baseline_reset_at (ou tudo, se baseline_reset_at
        for None)
    drawdown_pct = 0                                   se cumulative >= 0
                 = -cumulative_pnl_usdt / baseline_capital_usdt * 100  senão

Só dispara (`tripped=True`) uma vez - not re-trava sozinho depois de
liberado. Só `clear_breaker()` (ação manual explícita, ex: botão
"reativar" no portal) desliga o estado, e ao fazer isso também
"re-arma" `baseline_reset_at` pra agora - senão o breaker destravaria e
retravaria no ciclo seguinte só porque o ledger histórico ainda soma o
mesmo prejuízo.

Escrita de estado atômica desde o início (arquivo novo, sem motivo pra
repetir a lacuna que o watchdog do testnet tem hoje).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from telegram_notify import send_telegram

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CB_STATE_FILE = DATA / "binance_live_circuit_breaker_state.json"

DEFAULT_STATE = {
    "tripped": False,
    "tripped_at": None,
    "drawdown_pct_at_trip": None,
    "cumulative_pnl_usdt_at_trip": None,
    "baseline_reset_at": None,
    "cleared_at": None,
    "cleared_by": None,
    "alerted": False,
}


def load_cb_state() -> dict:
    if not CB_STATE_FILE.exists():
        return dict(DEFAULT_STATE)
    try:
        raw = json.loads(CB_STATE_FILE.read_text(encoding="utf-8"))
        state = dict(DEFAULT_STATE)
        state.update(raw)
        return state
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_STATE)


def save_cb_state(state: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = CB_STATE_FILE.with_suffix(CB_STATE_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, CB_STATE_FILE)


def compute_drawdown_pct(
    ledger_rows: list[dict],
    baseline_capital_usdt: float,
    baseline_reset_at: str | None,
) -> tuple[float, float]:
    """Retorna (drawdown_pct, cumulative_realized_pnl_usdt)."""
    cutoff = None
    if baseline_reset_at:
        try:
            cutoff = datetime.fromisoformat(baseline_reset_at)
        except ValueError:
            cutoff = None

    cumulative = 0.0
    for row in ledger_rows:
        pnl_raw = row.get("pnl_usdt", "")
        if pnl_raw in ("", None):
            continue
        if cutoff is not None:
            exit_raw = row.get("exit_time", "")
            try:
                exit_dt = datetime.fromisoformat(exit_raw)
            except ValueError:
                continue
            if exit_dt.tzinfo is None:
                exit_dt = exit_dt.replace(tzinfo=timezone.utc)
            if exit_dt <= cutoff:
                continue
        try:
            cumulative += float(pnl_raw)
        except ValueError:
            continue

    if baseline_capital_usdt <= 0:
        return 0.0, cumulative
    drawdown_pct = max(0.0, -cumulative / baseline_capital_usdt * 100.0)
    return drawdown_pct, cumulative


def check_and_maybe_trip(
    ledger_rows: list[dict],
    baseline_capital_usdt: float,
    max_drawdown_pct: float,
) -> dict:
    """Chamado a cada ciclo do trader, ANTES de abrir posições novas.

    O alerta e a persistência de `tripped` andam juntos numa única
    `save_cb_state` (não duas, como numa versão anterior) - se o
    processo morrer entre enviar o Telegram e salvar, `tripped` nunca
    fica gravado como True sem o alerta correspondente, então o
    próximo ciclo recalcula do zero e tenta alertar de novo em vez de
    achar "já tripped" e desistir silenciosamente. Se já estiver
    tripped mas `alerted` for False (alerta falhou por rede/Telegram
    fora do ar), tenta reenviar a cada ciclo até confirmar - nunca dá
    só uma tentativa e desiste pra sempre."""
    state = load_cb_state()
    if state["tripped"]:
        if not state.get("alerted"):
            ok = send_telegram(
                "[LIVE] ALERTA (reenvio) - circuit breaker acionado em "
                f"{state.get('tripped_at')}: perda acumulada de "
                f"${-state.get('cumulative_pnl_usdt_at_trip', 0.0):.2f} "
                f"({state.get('drawdown_pct_at_trip', 0.0):.1f}% do capital-base). "
                "Abertura de posição nova PAUSADA. Reative manualmente no "
                "portal quando decidir."
            )
            if ok:
                state["alerted"] = True
                save_cb_state(state)
        return state

    drawdown_pct, cumulative = compute_drawdown_pct(
        ledger_rows, baseline_capital_usdt, state.get("baseline_reset_at")
    )
    if drawdown_pct < max_drawdown_pct:
        return state

    now = datetime.now(timezone.utc).isoformat()
    alerted = send_telegram(
        "[LIVE] ALERTA - circuit breaker acionado: perda acumulada de "
        f"${-cumulative:.2f} ({drawdown_pct:.1f}% do capital-base de "
        f"${baseline_capital_usdt:.2f}) passou do limite de "
        f"{max_drawdown_pct:.1f}%. Abertura de posição nova PAUSADA - "
        "posições existentes continuam sendo monitoradas. Reative "
        "manualmente no portal quando decidir."
    )
    state.update({
        "tripped": True,
        "tripped_at": now,
        "drawdown_pct_at_trip": drawdown_pct,
        "cumulative_pnl_usdt_at_trip": cumulative,
        "alerted": alerted,
    })
    save_cb_state(state)

    return state


def is_halted() -> bool:
    return bool(load_cb_state().get("tripped"))


def clear_breaker(cleared_by: str = "portal") -> dict:
    """Único caminho que zera `tripped`. Re-arma baseline_reset_at pra
    agora, senão o breaker destrava e retrava no próximo ciclo porque o
    ledger histórico continua somando o mesmo prejuízo."""
    now = datetime.now(timezone.utc).isoformat()
    state = dict(DEFAULT_STATE)
    state.update({
        "baseline_reset_at": now,
        "cleared_at": now,
        "cleared_by": cleared_by,
    })
    save_cb_state(state)
    return state
