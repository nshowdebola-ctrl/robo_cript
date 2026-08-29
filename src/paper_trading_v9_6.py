#!/usr/bin/env python3
"""
CRYPTO RADAR - PAPER TRADING V9.6
Motor forward financeiro.

IMPORTANTE:
- Não usa o CSV legado V8 para criar operações.
- Não inventa dados históricos.
- O ledger V9 recebe somente operações geradas pelo motor V9.
- Execução é PAPER ONLY.
"""
import csv, os, math
from datetime import datetime, timezone

BASE=os.path.abspath(os.path.join(os.path.dirname(__file__),".."))
LEDGER=os.path.join(BASE,"data","paper_trading_v9_financial_trades.csv")

FIELDS=[
"trade_id","scenario","symbol","entry_time","exit_time","entry_price","exit_price",
"quantity","notional","entry_fee_rate","exit_fee_rate","entry_fee","exit_fee",
"slippage_entry_pct","slippage_exit_pct","gross_return_pct","net_return_pct",
"gross_pnl","net_pnl","exit_reason","holding_hours"
]

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def ensure_ledger():
    os.makedirs(os.path.dirname(LEDGER),exist_ok=True)
    if not os.path.exists(LEDGER) or os.path.getsize(LEDGER)==0:
        with open(LEDGER,"w",newline="",encoding="utf-8") as f:
            csv.DictWriter(f,fieldnames=FIELDS).writeheader()

def next_id():
    ensure_ledger()
    with open(LEDGER,newline="",encoding="utf-8") as f:
        rows=csv.DictReader(f)
        ids=[]
        for r in rows:
            try: ids.append(int(r["trade_id"]))
            except: pass
    return str(max(ids)+1 if ids else 1)

def validate_positive(name,value):
    value=float(value)
    if not math.isfinite(value) or value<=0:
        raise ValueError(f"{name} deve ser > 0")
    return value

def close_trade(symbol,entry_price,exit_price,notional,
                entry_fee_rate=0.001,exit_fee_rate=0.001,
                slippage_entry_pct=0.0,slippage_exit_pct=0.0,
                scenario="V9_FORWARD",entry_time=None,exit_time=None,
                exit_reason="TIME"):
    ep=validate_positive("entry_price",entry_price)
    xp=validate_positive("exit_price",exit_price)
    no=validate_positive("notional",notional)
    ef_rate=float(entry_fee_rate); xf_rate=float(exit_fee_rate)
    se=float(slippage_entry_pct); sx=float(slippage_exit_pct)

    # Preços efetivos: slippage é aplicado de forma adversa.
    effective_entry=ep*(1+se/100)
    effective_exit=xp*(1-sx/100)
    quantity=no/effective_entry

    entry_fee=no*ef_rate
    gross_pnl=quantity*(effective_exit-effective_entry)
    exit_notional=quantity*effective_exit
    exit_fee=exit_notional*xf_rate
    net_pnl=gross_pnl-entry_fee-exit_fee

    gross_return=gross_pnl/no*100
    net_return=net_pnl/no*100

    et=entry_time or utc_now()
    xt=exit_time or utc_now()
    try:
        a=datetime.fromisoformat(et.replace("Z","+00:00"))
        b=datetime.fromisoformat(xt.replace("Z","+00:00"))
        holding=(b-a).total_seconds()/3600
    except Exception:
        holding=0.0

    row={
        "trade_id":next_id(),"scenario":scenario,"symbol":str(symbol).upper(),
        "entry_time":et,"exit_time":xt,
        "entry_price":f"{ep:.12g}","exit_price":f"{xp:.12g}",
        "quantity":f"{quantity:.12g}","notional":f"{no:.12g}",
        "entry_fee_rate":f"{ef_rate:.8f}","exit_fee_rate":f"{xf_rate:.8f}",
        "entry_fee":f"{entry_fee:.12g}","exit_fee":f"{exit_fee:.12g}",
        "slippage_entry_pct":f"{se:.8f}","slippage_exit_pct":f"{sx:.8f}",
        "gross_return_pct":f"{gross_return:.10f}",
        "net_return_pct":f"{net_return:.10f}",
        "gross_pnl":f"{gross_pnl:.12g}","net_pnl":f"{net_pnl:.12g}",
        "exit_reason":exit_reason,"holding_hours":f"{holding:.6f}"
    }
    ensure_ledger()
    with open(LEDGER,"a",newline="",encoding="utf-8") as f:
        csv.DictWriter(f,fieldnames=FIELDS).writerow(row)
    return row

def main():
    print("="*100)
    print("CRYPTO RADAR - PAPER TRADING V9.6 -- MOTOR FINANCEIRO FORWARD")
    print("="*100)
    print(f"Ledger: {LEDGER}")
    print("Modo: PAPER ONLY")
    print("CSV legado V8: NÃO UTILIZADO PARA INVENTAR DADOS")
    ensure_ledger()
    print("Schema financeiro: OK")
    print("Nenhuma nova operação foi criada automaticamente.")
    print("Função close_trade() pronta para o scanner/motor forward.")
    print("="*100)

if __name__=="__main__":
    main()
