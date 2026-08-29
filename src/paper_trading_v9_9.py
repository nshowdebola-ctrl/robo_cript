#!/usr/bin/env python3
"""Crypto Radar V9.9: financial forward integration."""
import csv, os, math
from datetime import datetime, timezone

BASE=os.path.abspath(os.path.join(os.path.dirname(__file__),".."))
LEDGER=os.path.join(BASE,"data","paper_trading_v9_financial_trades.csv")
FIELDS=["trade_id","scenario","symbol","entry_time","exit_time","entry_price","exit_price","quantity","notional","entry_fee_rate","exit_fee_rate","entry_fee","exit_fee","slippage_entry_pct","slippage_exit_pct","gross_return_pct","net_return_pct","gross_pnl","net_pnl","exit_reason","holding_hours"]

def now(): return datetime.now(timezone.utc).isoformat()
def ensure():
    os.makedirs(os.path.dirname(LEDGER),exist_ok=True)
    if not os.path.exists(LEDGER) or os.path.getsize(LEDGER)==0:
        with open(LEDGER,"w",newline="",encoding="utf-8") as f: csv.DictWriter(f,fieldnames=FIELDS).writeheader()
def next_id():
    ensure(); ids=[]
    with open(LEDGER,newline="",encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try: ids.append(int(r["trade_id"]))
            except: pass
    return str(max(ids)+1 if ids else 1)
def positive(x,n):
    x=float(x)
    if not math.isfinite(x) or x<=0: raise ValueError(f"{n} deve ser > 0")
    return x
def open_trade(symbol,entry_price,notional,scenario="V9_FORWARD",entry_fee_rate=0.001,slippage_entry_pct=0.0,entry_time=None):
    ep=positive(entry_price,"entry_price"); no=positive(notional,"notional")
    fee=float(entry_fee_rate); slip=float(slippage_entry_pct)
    qty=no/(ep*(1+slip/100))
    return {"trade_id":next_id(),"scenario":scenario,"symbol":str(symbol).upper(),"entry_time":entry_time or now(),"entry_price":ep,"quantity":qty,"notional":no,"entry_fee_rate":fee,"entry_fee":no*fee,"slippage_entry_pct":slip}
def close_trade(p,exit_price,exit_fee_rate=0.001,slippage_exit_pct=0.0,exit_time=None,exit_reason="TIME"):
    xp=positive(exit_price,"exit_price"); fee=float(exit_fee_rate); slip=float(slippage_exit_pct)
    ee=p["entry_price"]*(1+p["slippage_entry_pct"]/100); ex=xp*(1-slip/100)
    qty=p["quantity"]; no=p["notional"]; entry_fee=p["entry_fee"]
    gross=qty*(ex-ee); exit_notional=qty*ex; exit_fee=exit_notional*fee; net=gross-entry_fee-exit_fee
    et=p["entry_time"]; xt=exit_time or now()
    try: hours=max(0,(datetime.fromisoformat(xt.replace("Z","+00:00"))-datetime.fromisoformat(et.replace("Z","+00:00"))).total_seconds()/3600)
    except: hours=0.0
    row={"trade_id":p["trade_id"],"scenario":p["scenario"],"symbol":p["symbol"],"entry_time":et,"exit_time":xt,"entry_price":f'{p["entry_price"]:.12g}',"exit_price":f"{xp:.12g}","quantity":f"{qty:.12g}","notional":f"{no:.12g}","entry_fee_rate":f'{p["entry_fee_rate"]:.8f}',"exit_fee_rate":f"{fee:.8f}","entry_fee":f"{entry_fee:.12g}","exit_fee":f"{exit_fee:.12g}","slippage_entry_pct":f'{p["slippage_entry_pct"]:.8f}',"slippage_exit_pct":f"{slip:.8f}","gross_return_pct":f"{gross/no*100:.10f}","net_return_pct":f"{net/no*100:.10f}","gross_pnl":f"{gross:.12g}","net_pnl":f"{net:.12g}","exit_reason":str(exit_reason),"holding_hours":f"{hours:.6f}"}
    ensure()
    with open(LEDGER,"a",newline="",encoding="utf-8") as f: csv.DictWriter(f,fieldnames=FIELDS).writerow(row)
    return row
def main():
    print("="*100); print("CRYPTO RADAR - PAPER TRADING V9.9 -- INTEGRAÇÃO FINANCEIRA FORWARD"); print("="*100)
    ensure(); print(f"Ledger: {LEDGER}"); print("Modo: PAPER ONLY"); print("Ordens reais: NÃO"); print("CSV legado V8: NÃO utilizado"); print("Funções: open_trade(), close_trade()"); print("="*100)
if __name__=="__main__": main()
