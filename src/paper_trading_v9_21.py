#!/usr/bin/env python3
"""
CRYPTO RADAR - PAPER TRADING V9.21
ORQUESTRADOR FORWARD SEGURO

Fluxo:
  scanner_v3.py
      -> V9.20.1 (se instalado) ou V9.20
      -> V9.18 monitor/close (sempre roda, independe do preflight)
      -> preflight de segurança (avaliado pós-monitor)
      -> V9.17 executor (só roda se o preflight aprovar)
      -> V9.19 auditoria

Princípios:
- PAPER ONLY. Nunca envia ordem real.
- Não usa o CSV legado V8.
- Não cria dados financeiros.
- Usa lock para impedir dois ciclos simultâneos.
- Monitorar/fechar posições existentes nunca fica refém do preflight:
  fechar uma posição vencida/stopada não é uma ação arriscada.
- Nunca executa V9.17 se o preflight encontrar sinais acionáveis
  semanticamente duplicados (símbolo + entry_time + timeframe) ou um
  volume de sinais muito acima da capacidade do sistema (20x
  MAX_POSITIONS - teto de sanidade, não limite de vagas). O V9.17 já
  limita quantas posições realmente abre por ciclo às vagas livres.
- Sinais já associados a posição aberta ou trade fechado, ou com
  entry_time mais velho que MAX_SIGNAL_AGE_HOURS (24h), não contam
  como acionáveis.
- Falha em qualquer etapa crítica interrompe o ciclo.
"""

from __future__ import annotations

import csv
import fcntl
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from paper_trading_v9_17 import MAX_POSITIONS

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

LOCK_FILE = DATA / "v9_forward_orchestrator.lock"
LOG_FILE = DATA / "v9_21_orchestrator.log"

SCANNER = ROOT / "src" / "scanner_v3.py"
ADAPTER_201 = ROOT / "src" / "scanner_v3_to_v9_20_1.py"
ADAPTER_200 = ROOT / "src" / "scanner_v3_to_v9.py"
EXECUTOR = ROOT / "src" / "paper_trading_v9_17.py"
MONITOR = ROOT / "src" / "paper_trading_v9_18.py"
AUDITOR = ROOT / "src" / "paper_trading_v9_19.py"

SIGNALS = DATA / "forward_signals.csv"
OPEN_FILE = DATA / "paper_trading_v9_open_positions.csv"
LEDGER = DATA / "paper_trading_v9_financial_trades.csv"

SIGNAL_FIELDS = {
    "signal_id", "scenario", "symbol", "entry_time",
    "entry_price", "timeframe", "score", "confidence", "signal"
}

# Mesma janela do MAX_HOLD_HOURS da V9.17: um sinal cujo entry_time já
# passou desse limite não é mais uma entrada nova válida, é sinal expirado.
MAX_SIGNAL_AGE_HOURS = 24


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def is_fresh(entry_time: str) -> bool:
    dt = parse_dt(entry_time)
    if dt is None:
        return False
    age_hours = (utc_now() - dt).total_seconds() / 3600.0
    return age_hours <= MAX_SIGNAL_AGE_HOURS


def stamp() -> str:
    return utc_now().isoformat()


def log(message: str) -> None:
    line = f"[{stamp()}] {message}"
    print(line, flush=True)
    DATA.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run_step(label: str, script: Path) -> int:
    if not script.exists():
        log(f"ERRO: etapa {label}: arquivo não encontrado: {script}")
        return 127

    log(f"INÍCIO {label}: {script.name}")

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        stdout=None,
        stderr=None,
        check=False,
    )

    log(f"FIM {label}: rc={result.returncode}")
    return result.returncode


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def ids_from_open() -> set[str]:
    return {
        row.get("signal_id", "").strip()
        for row in read_csv(OPEN_FILE)
        if row.get("signal_id", "").strip()
    }


def ids_from_ledger() -> set[str]:
    result = set()
    for row in read_csv(LEDGER):
        tid = row.get("trade_id", "").strip()
        if tid:
            # trade_id = f"{signal_id}_{exit_timestamp}"; signal_id pode
            # conter "_", então removemos só o sufixo de timestamp (sem "_").
            result.add(tid.rsplit("_", 1)[0])
    return result


def preflight() -> tuple[bool, str]:
    """
    Examina somente sinais que poderiam ser novos para o executor.

    A V9.17 já protege signal_id aberto/fechado, mas aqui adicionamos
    uma barreira independente contra dois sinais diferentes para o
    mesmo símbolo na mesma vela/horário.
    """
    rows = read_csv(SIGNALS)
    if not rows:
        return True, "sem sinais forward"

    missing = sorted(SIGNAL_FIELDS - set(rows[0]))
    if missing:
        return False, "schema de forward_signals.csv sem: " + ", ".join(missing)

    open_ids = ids_from_open()
    closed_ids = ids_from_ledger()

    actionable = []
    for row in rows:
        sid = row.get("signal_id", "").strip()
        if not sid:
            continue
        if row.get("signal", "").strip().upper() != "LONG":
            continue
        if sid in open_ids or sid in closed_ids:
            continue
        if not is_fresh(row.get("entry_time", "")):
            # Sinal nunca virou posição e já passou da janela de entrada
            # (MAX_SIGNAL_AGE_HOURS) - tratado como expirado, não acionável.
            continue
        actionable.append(row)

    semantic: dict[tuple[str, str, str], list[str]] = {}
    for row in actionable:
        key = (
            row.get("symbol", "").strip().upper(),
            row.get("entry_time", "").strip(),
            row.get("timeframe", "").strip(),
        )
        semantic.setdefault(key, []).append(row["signal_id"].strip())

    duplicates = {
        key: ids for key, ids in semantic.items() if len(ids) > 1
    }

    if duplicates:
        details = []
        for key, ids in sorted(duplicates.items()):
            details.append(f"{key[0]} {key[1]} {key[2]} -> {', '.join(ids)}")
        return False, (
            "SINAIS ACIONÁVEIS DUPLICADOS:\n  - " +
            "\n  - ".join(details)
        )

    # Limite defensivo: não é sobre quantos sinais existem no total (isso é
    # esperado crescer organicamente sempre que o mercado gera mais sinais
    # do que vagas livres), e sim sobre uma explosão anormal de entradas
    # (ex: bug gerando sinais espúrios). O V9.17 já só abre até as vagas
    # realmente livres (MAX_POSITIONS - posições abertas) a cada ciclo, e
    # candidatos excedentes seguem elegíveis nos próximos ciclos até serem
    # abertos ou expirarem (MAX_SIGNAL_AGE_HOURS). Um total muito acima da
    # capacidade do sistema (aqui, 20x MAX_POSITIONS) é que indica anomalia.
    sanity_ceiling = MAX_POSITIONS * 20
    if len(actionable) > sanity_ceiling:
        return False, (
            f"{len(actionable)} sinais acionáveis excedem o teto de "
            f"sanidade ({sanity_ceiling}, 20x MAX_POSITIONS={MAX_POSITIONS}) "
            "neste orquestrador - possível anomalia na geração de sinais."
        )

    return True, f"{len(actionable)} sinais acionáveis sem duplicidade"


def acquire_lock():
    DATA.mkdir(parents=True, exist_ok=True)
    fh = LOCK_FILE.open("a+", encoding="utf-8")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None

    fh.seek(0)
    fh.truncate()
    fh.write(f"pid={os.getpid()}\nstarted={stamp()}\n")
    fh.flush()
    return fh


def main() -> int:
    print("=" * 100)
    print("CRYPTO RADAR - PAPER TRADING V9.21 -- ORQUESTRADOR FORWARD SEGURO")
    print("=" * 100)
    print("Modo: PAPER ONLY")
    print("Ordens reais: NÃO")
    print("CSV legado V8: NÃO UTILIZADO")
    print(f"Projeto: {ROOT}")
    print(f"Lock:    {LOCK_FILE}")
    print(f"Log:     {LOG_FILE}")
    print("-" * 100)

    lock = acquire_lock()
    if lock is None:
        print("ABORTADO: outro ciclo V9.21 já está em execução.")
        return 2

    try:
        log("CICLO V9.21 iniciado")

        # 1. Scanner V3 é a única fonte de sinais.
        rc = run_step("SCANNER_V3", SCANNER)
        if rc != 0:
            log("ABORTADO: scanner_v3 falhou.")
            return rc

        # 2. Preferir adapter corrigido V9.20.1.
        adapter = ADAPTER_201 if ADAPTER_201.exists() else ADAPTER_200
        adapter_name = "V9.20.1" if adapter == ADAPTER_201 else "V9.20"
        rc = run_step(f"ADAPTER_{adapter_name}", adapter)
        if rc != 0:
            log(f"ABORTADO: adapter {adapter_name} falhou.")
            return rc

        # 3. Monitorar/fechar posições existentes SEMPRE roda, mesmo que haja
        # backlog de sinais novos travando a abertura de posições - fechar
        # posições vencidas/stopadas não é uma ação arriscada e não deve
        # ficar refém do limite defensivo de sinais acionáveis.
        rc = run_step("MONITOR_CLOSE_V9.18", MONITOR)
        if rc != 0:
            log("ABORTADO: V9.18 falhou.")
            return rc

        # 4. Só a abertura de posições novas (V9.17) fica condicionada ao
        # preflight - avaliado após o monitor, pois posições/ledger mudaram.
        ok, reason = preflight()
        log(f"PREFLIGHT_PÓS_MONITOR: {'OK' if ok else 'BLOQUEADO'} - {reason}")
        if not ok:
            print()
            print("PREFLIGHT BLOQUEOU O EXECUTOR (abertura de posições novas).")
            print("Posições existentes já foram monitoradas/fechadas normalmente.")
            return 3

        # 5. Abrir somente sinais seguros.
        rc = run_step("EXECUTOR_V9.17", EXECUTOR)
        if rc != 0:
            log("ABORTADO: V9.17 falhou.")
            return rc

        # 6. Auditoria estrutural final.
        rc = run_step("AUDITORIA_V9.19", AUDITOR)
        if rc != 0:
            log("AUDITORIA V9.19 retornou erro.")
            return rc

        log("CICLO V9.21 concluído com sucesso.")
        print("=" * 100)
        print("V9.21 CONCLUÍDA: ciclo forward seguro.")
        print("Nenhuma ordem real foi enviada.")
        print("=" * 100)
        return 0

    finally:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        finally:
            lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
