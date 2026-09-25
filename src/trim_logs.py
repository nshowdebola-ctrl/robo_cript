#!/usr/bin/env python3
"""
CRYPTO RADAR - LIMPEZA DIÁRIA DE LOGS

Mantém em data/*.log só as linhas recentes (KEEP_DAYS_DEFAULT = 1 dia).
Exceções em KEEP_DAYS:
    - binance_live.log: 8 dias (a revisão semanal conta as proteções da
      semana nele e é o registro de auditoria do robô);
    - logs da própria revisão semanal: 60 dias (1 entrada por semana).

Cada linha vale pela data no começo dela ([ISO], ISO sem colchetes ou o
formato do servidor PHP "[Sat Aug 29 11:55:39 2026]"). Linhas sem data
(cabeçalho, traceback) seguem a última linha com data, pra um erro não ficar
cortado pela metade. Log sem nenhuma data é esvaziado se não é escrito há
mais tempo que o prazo.

O arquivo é regravado no mesmo lugar (mesmo inode): o loop do live e o
servidor PHP continuam escrevendo nele normalmente. Roda 1x/dia via cron.

Uso:
  python3 src/trim_logs.py            # limpa
  python3 src/trim_logs.py --dry-run  # só mostra o que faria
"""

from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
KEEP_DAYS_DEFAULT = 1
KEEP_DAYS = {
    "binance_live.log": 8,
    "weekly_review.log": 60,
    "cron_weekly_review.log": 60,
}

ISO = re.compile(r"^\[?(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?)")
PHP = re.compile(r"^\[(\w{3} \w{3} +\d{1,2} \d{2}:\d{2}:\d{2} \d{4})\]")


def line_time(line: str) -> datetime | None:
    m = ISO.match(line)
    if m:
        try:
            t = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
        except ValueError:
            return None
        return t if t.tzinfo else t.astimezone()      # sem fuso = hora local da máquina
    m = PHP.match(line)
    if m:
        try:
            return datetime.strptime(m.group(1), "%a %b %d %H:%M:%S %Y").astimezone()
        except ValueError:
            return None
    return None


def trim(path: Path, keep_days: int, dry: bool) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    with path.open("r+", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
        kept, keep, any_date = [], False, False
        for line in lines:
            t = line_time(line)
            if t is not None:
                any_date = True
                keep = t >= cutoff
            if keep:
                kept.append(line)
        if not any_date:
            idle_days = (time.time() - path.stat().st_mtime) / 86400
            if idle_days <= keep_days or not lines:
                return f"{path.name}: sem datas, escrito há {idle_days:.1f} dia(s) - mantido"
            kept = []
        if len(kept) == len(lines):
            return f"{path.name}: nada a remover ({len(lines)} linhas)"
        before = path.stat().st_size
        if not dry:
            fh.seek(0)
            fh.writelines(kept)
            fh.truncate()
    after = path.stat().st_size if not dry else sum(len(l.encode()) for l in kept)
    return (f"{path.name}: {len(lines)} -> {len(kept)} linhas "
            f"({before / 1e6:.1f} MB -> {after / 1e6:.1f} MB, mantém {keep_days} dia(s))")


def main() -> int:
    dry = "--dry-run" in sys.argv
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    for path in sorted(DATA.glob("*.log")):
        try:
            msg = trim(path, KEEP_DAYS.get(path.name, KEEP_DAYS_DEFAULT), dry)
        except Exception as exc:
            msg = f"{path.name}: ERRO {type(exc).__name__}: {exc}"
        print(f"{stamp} {'[simulação] ' if dry else ''}{msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
