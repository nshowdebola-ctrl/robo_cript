#!/usr/bin/env python3
"""
CRYPTO RADAR - PAPER TRADING V9.2
Validador financeiro de trades produzidos pela V9.

Rejeita silenciosamente? NÃO. Toda inconsistência é reportada.
"""
from __future__ import annotations
import argparse,csv,math,os
from datetime import datetime

REQ={"trade_id","symbol","entry_time","exit_time","entry_price","exit_price",
     "quantity","notional","entry_fee","exit_fee","fee_rate","gross_pnl",
     "gross_return_pct","net_pnl","net_return_pct","capital_before","capital_after"}

def f(x):
    try:
        y=float(x); return y if math.isfinite(y) else None
    except: return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",default="data/paper_trading_v9_trades.csv")
    args=ap.parse_args()
    if not os.path.exists(args.input):
        raise SystemExit(f"Arquivo não encontrado: {args.input}")
    with open(args.input,newline="",encoding="utf-8-sig") as h:
        rows=list(csv.DictReader(h))
    print("="*100)
    print("CRYPTO RADAR - PAPER TRADING V9.2 -- VALIDADOR FINANCEIRO")
    print("="*100)
    print(f"Trades: {len(rows)}")
    if not rows:
        print("VEREDITO: SEM DADOS")
        return 1
    miss=REQ-set(rows[0])
    if miss:
        print("Campos ausentes:",", ".join(sorted(miss)))
        print("VEREDITO: REPROVADO")
        return 1

    bad=0; mismatches=0
    for i,r in enumerate(rows,2):
        vals=[f(r[k]) for k in REQ if k not in {"symbol","trade_id"}]
        if any(v is None for v in vals): bad+=1; continue
        n=f(r["notional"]); q=f(r["quantity"]); ep=f(r["entry_price"])
        xp=f(r["exit_price"]); ef=f(r["entry_fee"]); xf=f(r["exit_fee"])
        gp=f(r["gross_pnl"]); np=f(r["net_pnl"])
        if min(n,q,ep,xp,ef,xf) < 0: bad+=1
        calc_gross=q*(xp-ep)
        calc_net=calc_gross-ef-xf
        if abs(calc_gross-gp)>max(1e-8,abs(gp)*1e-6): mismatches+=1
        if abs(calc_net-np)>max(1e-8,abs(np)*1e-6): mismatches+=1

    print(f"Dados inválidos: {bad}")
    print(f"Inconsistências matemáticas: {mismatches}")
    verdict = bad==0 and mismatches==0
    print("VEREDITO:", "APROVADO PARA AUDITORIA" if verdict else "NÃO APROVADO")
    print("Aprovação significa apenas consistência matemática do dataset; não significa estratégia lucrativa.")
    print("="*100)
    return 0 if verdict else 1

if __name__=="__main__":
    raise SystemExit(main())
