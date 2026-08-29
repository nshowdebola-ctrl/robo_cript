#!/usr/bin/env python3
import csv, os, math

BASE=os.path.abspath(os.path.join(os.path.dirname(__file__),".."))
LEDGER=os.path.join(BASE,"data","paper_trading_v9_financial_trades.csv")

REQ={"trade_id","symbol","entry_time","exit_time","entry_price","exit_price",
"quantity","notional","entry_fee_rate","exit_fee_rate","entry_fee","exit_fee",
"gross_return_pct","net_return_pct","gross_pnl","net_pnl"}

def n(x):
    try:
        v=float(x); return v if math.isfinite(v) else None
    except: return None

def main():
    print("="*100)
    print("CRYPTO RADAR - PAPER TRADING V9.7 -- AUDITORIA DO LEDGER")
    print("="*100)
    if not os.path.exists(LEDGER):
        print("Ledger inexistente.")
        raise SystemExit(1)
    with open(LEDGER,newline="",encoding="utf-8") as f:
        rd=csv.DictReader(f); fields=set(rd.fieldnames or []); rows=list(rd)
    miss=REQ-fields
    print(f"Trades: {len(rows)}")
    if miss:
        print("Campos ausentes:",", ".join(sorted(miss))); raise SystemExit(1)
    seen=set(); dup=0; bad=0
    for r in rows:
        if r["trade_id"] in seen: dup+=1
        seen.add(r["trade_id"])
        ep,xp,q,no=n(r["entry_price"]),n(r["exit_price"]),n(r["quantity"]),n(r["notional"])
        er,xr=n(r["entry_fee"]),n(r["exit_fee"])
        gr,nr,gp,np=n(r["gross_return_pct"]),n(r["net_return_pct"]),n(r["gross_pnl"]),n(r["net_pnl"])
        if None in (ep,xp,q,no,er,xr,gr,nr,gp,np) or ep<=0 or xp<=0 or q<=0 or no<=0:
            bad+=1; continue
        calc_gp=q*(xp-xp*0+0) # placeholder replaced below
        # O ledger registra preços de referência e slippage separadamente.
        se=n(r["slippage_entry_pct"]) or 0
        sx=n(r["slippage_exit_pct"]) or 0
        ee=ep*(1+se/100); ex=xp*(1-sx/100)
        calc_q=no/ee
        calc_ef=no*(n(r["entry_fee_rate"]) or 0)
        calc_gross=calc_q*(ex-ee)
        calc_exit_no=calc_q*ex
        calc_xf=calc_exit_no*(n(r["exit_fee_rate"]) or 0)
        calc_np=calc_gross-calc_ef-calc_xf
        calc_gr=calc_gross/no*100
        calc_nr=calc_np/no*100
        if abs(q-calc_q)>1e-8 or abs(gp-calc_gross)>1e-7 or abs(np-calc_np)>1e-7 or abs(gr-calc_gr)>1e-7 or abs(nr-calc_nr)>1e-7 or abs(er-calc_ef)>1e-7 or abs(xr-calc_xf)>1e-7:
            bad+=1
    print(f"Duplicidades: {dup}")
    print(f"Inconsistências: {bad}")
    print("VEREDITO:", "APROVADO" if not dup and not bad else "NÃO APROVADO")
    print("="*100)

if __name__=="__main__": main()
