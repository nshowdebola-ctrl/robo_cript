#!/usr/bin/env python3
import csv, os, math

BASE=os.path.abspath(os.path.join(os.path.dirname(__file__),".."))
LEDGER=os.path.join(BASE,"data","paper_trading_v9_financial_trades.csv")

REQ={
"trade_id","symbol","entry_time","exit_time","entry_price","exit_price",
"quantity","notional","entry_fee_rate","exit_fee_rate","entry_fee","exit_fee",
"gross_return_pct","net_return_pct","gross_pnl","net_pnl"
}

def f(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except:
        return None

def main():
    print("="*100)
    print("CRYPTO RADAR - PAPER TRADING V9.4 -- VALIDADOR FINANCEIRO")
    print("="*100)

    if not os.path.exists(LEDGER):
        raise SystemExit(f"Ledger não encontrado: {LEDGER}")

    with open(LEDGER,newline="",encoding="utf-8") as fh:
        reader=csv.DictReader(fh)
        fields=set(reader.fieldnames or [])
        rows=list(reader)

    missing=sorted(REQ-fields)
    print(f"Trades financeiros: {len(rows)}")
    print(f"Schema encontrado: {len(fields)} campos")

    if missing:
        print("Campos ausentes: "+", ".join(missing))
        raise SystemExit(1)

    if not rows:
        print("Ledger vazio: schema financeiro V9 está correto.")
        print("Nenhuma operação foi inventada ou corrigida.")
        print("VEREDITO: APTO PARA RECEBER NOVOS TRADES")
        print("="*100)
        return

    dup=0; bad=0; seen=set()
    for r in rows:
        tid=r["trade_id"]
        if tid in seen: dup+=1
        seen.add(tid)

        ep,xp,q,notional=f(r["entry_price"]),f(r["exit_price"]),f(r["quantity"]),f(r["notional"])
        ef,xf=f(r["entry_fee"]),f(r["exit_fee"])
        if None in (ep,xp,q,notional,ef,xf) or min(ep,xp,q,notional)<0:
            bad+=1; continue

        gross=(xp/ep-1)*100 if ep else None
        gross_pnl=notional*gross/100 if gross is not None else None
        net_pnl=gross_pnl-ef-xf if gross_pnl is not None else None
        net=(net_pnl/notional)*100 if notional else None

        rg,rn=f(r["gross_return_pct"]),f(r["net_return_pct"])
        pg,pn=f(r["gross_pnl"]),f(r["net_pnl"])
        if any(v is None for v in (rg,rn,pg,pn)) or abs(rg-gross)>1e-6 or abs(rn-net)>1e-6 or abs(pg-gross_pnl)>1e-6 or abs(pn-net_pnl)>1e-6:
            bad+=1

    print(f"Duplicidades: {dup}")
    print(f"Inconsistências financeiras: {bad}")
    ok=(dup==0 and bad==0)
    print("VEREDITO:", "APROVADO" if ok else "NÃO APROVADO")
    print("Nenhum dado foi corrigido silenciosamente.")
    print("="*100)

if __name__=="__main__":
    main()
