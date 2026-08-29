#!/usr/bin/env python3
"""Crypto Radar V9.14 - auditoria do ledger financeiro V9."""
import csv, os, math

BASE=os.path.abspath(os.path.join(os.path.dirname(__file__),".."))
LEDGER=os.path.join(BASE,"data","paper_trading_v9_financial_trades.csv")
REQ={"trade_id","symbol","entry_time","exit_time","entry_price","exit_price",
     "quantity","notional","entry_fee_rate","exit_fee_rate","entry_fee","exit_fee",
     "gross_return_pct","net_return_pct","gross_pnl","net_pnl"}

def num(x):
    try:
        y=float(x)
        return y if math.isfinite(y) else None
    except:
        return None

def main():
    print("="*100)
    print("CRYPTO RADAR - PAPER TRADING V9.14 -- AUDITORIA FINANCEIRA")
    print("="*100)
    if not os.path.exists(LEDGER):
        print("Ledger não existe.")
        return
    with open(LEDGER,newline="",encoding="utf-8") as f:
        rows=list(csv.DictReader(f))
    print(f"Trades financeiros: {len(rows)}")
    if not rows:
        print("Ledger vazio: aguardando primeiro ciclo forward.")
        print("VEREDITO: APTO")
        print("="*100)
        return

    dup=len(rows)-len({r.get("trade_id") for r in rows})
    bad=0
    math_bad=0
    for r in rows:
        if not REQ.issubset(r): bad+=1; continue
        vals=[num(r[k]) for k in ("entry_price","exit_price","quantity","notional","entry_fee","exit_fee","gross_pnl","net_pnl")]
        if any(v is None for v in vals): bad+=1; continue
        expected=float(r["gross_pnl"])-float(r["entry_fee"])-float(r["exit_fee"])
        if abs(expected-float(r["net_pnl"]))>1e-8: math_bad+=1
    print(f"Duplicidades: {dup}")
    print(f"Linhas estruturalmente inválidas: {bad}")
    print(f"Inconsistências P&L líquido: {math_bad}")
    ok=(dup==0 and bad==0 and math_bad==0)
    print("VEREDITO:", "APROVADO" if ok else "NÃO APROVADO")
    print("Auditoria usa somente o ledger financeiro V9.")
    print("="*100)

if __name__=="__main__":
    main()
