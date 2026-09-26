#!/usr/bin/env python3
"""
CRYPTO RADAR - BOT DO TELEGRAM QUE RESPONDE COMANDOS (só leitura)

Fica rodando e busca mensagens novas do bot (getUpdates, long polling -
não precisa de porta aberta nem webhook). Só responde ao TELEGRAM_CHAT_ID
de .telegram.env; mensagem de qualquer outro chat é ignorada sem resposta.

Comandos:
    /saldo     valor da conta, USDT livre, BNB, sobras
    /posicoes  posições abertas com % atual
    /hoje      trades fechados hoje (Brasília)
    /resumo    acerto, ganho/perda média, média por trade, acerto p/ empatar
    /regras    ajustes em vigor
    /status    loop, circuit breaker, pausas
    /revisao   prévia da revisão semanal (não mexe no estado da revisão)
    /ajuda     lista de comandos

NENHUM comando envia ordem, muda regra ou mexe no loop - isso fica só no
Admin. Saldo e preços pela API são só leitura (fetch_balance/fetch_ticker).

Uso: roda via cron a cada minuto com flock (se cair, o cron religa):
    * * * * * cd <repo> && flock -n /tmp/crypto-radar-telegram-bot.lock \
        .venv/bin/python3 src/telegram_bot.py >> data/telegram_bot.log 2>&1
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from binance_live_circuit_breaker import load_cb_state  # noqa: E402
from binance_live_executor import ENV_FILE, build_exchange, load_env  # noqa: E402
from binance_live_trader import (  # noqa: E402
    config_fields,
    load_live_config,
    realized_pnl_today,
    stop_cluster_pause_until,
)
from telegram_notify import load_env as load_telegram_env  # noqa: E402
from weekly_review import BRT, build_review, dt, read_csv, usd  # noqa: E402

DATA = ROOT / "data"
LEDGER = DATA / "binance_live_trades.csv"
OPEN_FILE = DATA / "binance_live_open_positions.csv"
LIVE_LOG = DATA / "binance_live.log"
PID_FILE = DATA / "binance_live_loop.pid"
STATE_FILE = DATA / "telegram_bot_state.json"

POLL_TIMEOUT = 50          # segundos que o Telegram segura o getUpdates
MAX_MESSAGE_AGE = 300      # ignora comando mais velho que isso (bot estava fora)


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


def api(token: str, method: str, params: dict, timeout: int = 15) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode("utf-8")
    with urllib.request.urlopen(url, data=data, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def exchange():
    ex = build_exchange(load_env(ENV_FILE))
    ex.load_markets()
    return ex


def price(ex, symbol: str) -> float | None:
    try:
        return float(ex.fetch_ticker(symbol)["last"])
    except Exception:
        return None


# ---------------------------------------------------------------- comandos

def cmd_saldo() -> str:
    ex = exchange()
    bal = ex.fetch_balance()
    tracked: dict[str, float] = {}
    for p in read_csv(OPEN_FILE):
        base = p["symbol"].split("/")[0].strip().upper()
        tracked[base] = tracked.get(base, 0.0) + float(p["quantity"] or 0)
    usdt_free = float(bal.get("USDT", {}).get("free") or 0)
    usdt_total = float(bal.get("total", {}).get("USDT") or 0)
    in_pos = bnb = leftovers = 0.0
    for asset, qty in bal.get("total", {}).items():
        if not qty or asset == "USDT" or f"{asset}/USDT" not in ex.markets:
            continue
        px = price(ex, f"{asset}/USDT")
        if px is None:
            continue
        pos_qty = min(qty, tracked.get(asset, 0.0))
        in_pos += pos_qty * px
        rest = (qty - pos_qty) * px
        if asset == "BNB":
            bnb += rest
        else:
            leftovers += rest
    total = usdt_total + in_pos + bnb + leftovers
    cfg = load_live_config()
    base = float(cfg.get("baseline_capital_usdt") or 0)
    lines = [
        f"Conta: {usd(total)}"
        + (f" ({(total / base - 1) * 100:+.1f}% sobre capital-base {usd(base)})" if base else ""),
        f"Posições abertas: {usd(in_pos)}",
        f"USDT livre: {usd(usdt_free)}",
        f"BNB fora das posições: {usd(bnb)}",
        f"Sobras: {usd(leftovers)}",
    ]
    return "\n".join(lines)


def cmd_posicoes() -> str:
    rows = read_csv(OPEN_FILE)
    if not rows:
        return "Nenhuma posição aberta."
    ex = exchange()
    now = datetime.now(timezone.utc)
    lines, pcts = [], []
    for p in rows:
        entry = float(p["entry_price"])
        px = price(ex, p["symbol"])
        t = dt(p["entry_time"])
        age = f"{(now - t).total_seconds() / 3600:.0f}h" if t else "?"
        if px is None:
            lines.append(f"{p['symbol']:<11} ? ({age})")
            continue
        pct = (px / entry - 1) * 100
        pcts.append(pct)
        lines.append(f"{p['symbol']:<11} {pct:+.2f}% ({age})")
    if pcts:
        lines.append(f"Média: {sum(pcts) / len(pcts):+.2f}% em {len(pcts)} posições")
    return "\n".join(lines)


def cmd_hoje() -> str:
    now = datetime.now(timezone.utc)
    today = now.astimezone(BRT).date()
    rows = [r for r in read_csv(LEDGER) if (t := dt(r["exit_time"])) and t.astimezone(BRT).date() == today]
    if not rows:
        return f"Nenhum trade fechado hoje ({today:%d/%m})."
    lines = [f"Hoje {today:%d/%m}:"]
    for r in rows:
        t = dt(r["exit_time"]).astimezone(BRT)
        lines.append(
            f"{t:%H:%M} {r['symbol']:<11} {r['exit_reason']:<6} "
            f"{float(r['gross_return_pct']):+.2f}% {usd(float(r['pnl_usdt']), True)}"
        )
    pnl = sum(float(r["pnl_usdt"]) for r in rows)
    wins = sum(float(r["pnl_usdt"]) > 0 for r in rows)
    lines.append(f"Total: {len(rows)} trades, {wins} positivos, {usd(pnl, True)}")
    return "\n".join(lines)


def cmd_resumo() -> str:
    rows = read_csv(LEDGER)
    if not rows:
        return "Nenhum trade fechado ainda."
    g = [float(r["gross_return_pct"]) for r in rows]
    wins = [x for x in g if x > 0]
    losses = [x for x in g if x <= 0]
    avg_w = sum(wins) / len(wins) if wins else 0.0
    avg_l = sum(losses) / len(losses) if losses else 0.0
    breakeven = abs(avg_l) / (avg_w + abs(avg_l)) * 100 if wins and losses else None
    pnl = sum(float(r["pnl_usdt"]) for r in rows)
    lines = [
        f"{len(rows)} trades | acerto {len(wins) / len(g):.0%}",
        f"Ganho médio {avg_w:+.2f}% | perda média {avg_l:+.2f}%",
        f"Média por trade: {sum(g) / len(g):+.2f}%",
    ]
    if breakeven is not None:
        lines.append(f"Acerto mínimo pra empatar: {breakeven:.0f}%")
    lines.append(f"P&L realizado: {usd(pnl, True)}")
    if len(rows) < 100:
        lines.append(f"Faltam {100 - len(rows)} trades pra reavaliar as regras.")
    return "\n".join(lines)


def cmd_regras() -> str:
    cfg = load_live_config()
    lines = []
    for f in config_fields():
        v = cfg.get(f["key"])
        if f["type"] == "bool":
            v = "sim" if v else "não"
        elif f["type"] == "list":
            v = ", ".join(v) if v else "-"
        unit = f.get("unit", "")
        lines.append(f"{f['label']}: {v}{' ' + unit if unit and f['type'] not in ('bool', 'list') else ''}")
    return "\n".join(lines)


def cmd_status() -> str:
    now = datetime.now(timezone.utc)
    lines = []
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        lines.append(f"Loop: rodando (pid {pid})")
    except Exception:
        lines.append("Loop: PARADO")
    last = None
    if LIVE_LOG.exists():
        with LIVE_LOG.open("rb") as fh:
            fh.seek(max(0, LIVE_LOG.stat().st_size - 4000))
            tail = fh.read().decode("utf-8", errors="replace").splitlines()
        for line in reversed(tail):
            if line.startswith("[") and "]" in line:
                last = dt(line[1:line.index("]")])
                if last:
                    break
    if last:
        lines.append(f"Último registro no log: há {(now - last).total_seconds() / 60:.0f} min")
    cb = load_cb_state()
    lines.append("Circuit breaker: " + (f"DISPARADO em {cb.get('tripped_at')}" if cb.get("tripped") else "ok"))
    cfg = load_live_config()
    ledger = read_csv(LEDGER)
    pnl_today = realized_pnl_today(ledger, now)
    limit = float(cfg["daily_loss_limit_usdt"])
    lines.append(
        f"Perda do dia (UTC): {usd(pnl_today, True)} / limite -{usd(limit)}"
        + (" - COMPRAS PARADAS" if pnl_today <= -limit else "")
    )
    pause = stop_cluster_pause_until(ledger, now)
    if pause:
        lines.append(f"Pausa por stops em série até {pause.astimezone(BRT):%H:%M} (Brasília)")
    local = now.astimezone(BRT)
    if cfg.get("no_buy_enabled") and cfg["no_buy_start_hour"] <= local.hour <= cfg["no_buy_end_hour"]:
        lines.append(f"Horário sem compra agora ({cfg['no_buy_start_hour']}h-{cfg['no_buy_end_hour']}h59)")
    lines.append(f"Posições abertas: {len(read_csv(OPEN_FILE))}/{cfg['max_positions']}")
    return "\n".join(lines)


def cmd_revisao() -> str:
    text, _ = build_review(datetime.now(timezone.utc))
    return text


def cmd_ajuda() -> str:
    return (
        "Comandos (só consulta, nada envia ordem):\n"
        "/saldo - valor da conta\n"
        "/posicoes - posições abertas\n"
        "/hoje - trades de hoje\n"
        "/resumo - acerto e média por trade\n"
        "/regras - ajustes em vigor\n"
        "/status - loop e proteções\n"
        "/revisao - prévia da revisão semanal"
    )


COMMANDS = {
    "/saldo": cmd_saldo,
    "/posicoes": cmd_posicoes,
    "/hoje": cmd_hoje,
    "/resumo": cmd_resumo,
    "/regras": cmd_regras,
    "/status": cmd_status,
    "/revisao": cmd_revisao,
    "/ajuda": cmd_ajuda,
    "/start": cmd_ajuda,
    "/help": cmd_ajuda,
}

MENU = [
    ("saldo", "Valor da conta"),
    ("posicoes", "Posições abertas"),
    ("hoje", "Trades de hoje"),
    ("resumo", "Acerto e média por trade"),
    ("regras", "Ajustes em vigor"),
    ("status", "Loop e proteções"),
    ("revisao", "Prévia da revisão semanal"),
    ("ajuda", "Lista de comandos"),
]


def answer(text: str) -> str:
    word = text.strip().split()[0].lower() if text.strip() else ""
    word = word.split("@")[0]  # /saldo@NomeDoBot
    func = COMMANDS.get(word)
    if func is None:
        return "Não conheço esse comando.\n\n" + cmd_ajuda()
    try:
        return func()
    except Exception as exc:
        return f"Erro ao responder {word}: {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- loop

def load_offset() -> int:
    try:
        return int(json.loads(STATE_FILE.read_text(encoding="utf-8")).get("offset", 0))
    except Exception:
        return 0


def save_offset(offset: int) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"offset": offset}), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def main() -> int:
    env = load_telegram_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = env.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        log("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID ausentes em .telegram.env - encerrado.")
        return 1
    try:
        api(token, "setMyCommands", {"commands": json.dumps(
            [{"command": c, "description": d} for c, d in MENU])})
    except Exception as exc:
        log(f"AVISO: não registrou o menu de comandos ({type(exc).__name__}: {exc})")
    log(f"Bot iniciado (pid {os.getpid()}).")

    offset = load_offset()
    while True:
        try:
            resp = api(token, "getUpdates",
                       {"offset": offset, "timeout": POLL_TIMEOUT, "allowed_updates": '["message"]'},
                       timeout=POLL_TIMEOUT + 15)
        except Exception as exc:
            log(f"AVISO getUpdates: {type(exc).__name__}: {exc}")
            time.sleep(10)
            continue
        for upd in resp.get("result", []):
            offset = max(offset, int(upd["update_id"]) + 1)
            save_offset(offset)
            msg = upd.get("message") or {}
            from_chat = str((msg.get("chat") or {}).get("id", ""))
            text = msg.get("text") or ""
            if from_chat != chat_id:
                log(f"Ignorado: mensagem de chat desconhecido {from_chat}.")
                continue
            age = time.time() - int(msg.get("date", 0))
            if age > MAX_MESSAGE_AGE:
                log(f"Ignorado: '{text[:30]}' de {age / 60:.0f} min atrás (bot estava fora).")
                continue
            log(f"Comando: {text[:50]}")
            reply = answer(text)
            try:
                api(token, "sendMessage", {"chat_id": chat_id, "text": reply[:4000]})
            except Exception as exc:
                log(f"AVISO sendMessage: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
