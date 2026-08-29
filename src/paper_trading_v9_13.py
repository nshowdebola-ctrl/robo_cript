#!/usr/bin/env python3
"""Crypto Radar V9.13 - executor forward a partir de sinais fechados.

Formato esperado do CSV:
symbol,entry_price,exit_price,entry_time,exit_time,scenario,exit_reason

Esta versão é deliberadamente PAPER ONLY.
"""
import csv, os
from datetime import datetime, timezone

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SIGNALS = os.path.join(BASE, "data", "forward_signals.csv")

def utc(s):
    if not s:
        return datetime.now(timezone.utc).isoformat()
    d = datetime.fromisoformat(s.replace("Z","+00:00"))
    if d.tzinfo is None:
        d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat()

def validate_signal(row):
    for k in ("symbol","entry_price","exit_price"):
        if not row.get(k):
            raise ValueError(f"Sinal sem {k}")
    ep=float(row["entry_price"]); xp=float(row["exit_price"])
    if ep <= 0 or xp <= 0:
        raise ValueError("Preços devem ser positivos")
    return {
        "symbol":row["symbol"].strip().upper(),
        "entry_price":ep, "exit_price":xp,
        "entry_time":utc(row.get("entry_time")),
        "exit_time":utc(row.get("exit_time")),
        "scenario":row.get("scenario") or "V9_FORWARD",
        "exit_reason":row.get("exit_reason") or "TIME",
    }

def load_signals(path):
    if not os.path.exists(path):
        return []
    with open(path,newline="",encoding="utf-8-sig") as f:
        return [validate_signal(r) for r in csv.DictReader(f)]

def main():
    print("="*100)
    print("CRYPTO RADAR - PAPER TRADING V9.13 -- FORWARD SIGNAL GATE")
    print("="*100)
    print(f"Arquivo de sinais: {SIGNALS}")
    print("Modo: PAPER ONLY")
    print("Ordens reais: NÃO")
    rows=load_signals(SIGNALS)
    print(f"Sinais válidos encontrados: {len(rows)}")
    if rows:
        print("O V9.13 valida o contrato; o V9.12 é responsável pelo registro financeiro.")
    else:
        print("Nenhum sinal forward ainda. Nenhum trade foi inventado.")
    print("="*100)

if __name__=="__main__":
    main()
