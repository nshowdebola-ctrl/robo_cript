#!/usr/bin/env python3
import csv, os, math
BASE=os.path.abspath(os.path.join(os.path.dirname(__file__),".."))
LEDGER=os.path.join(BASE,"data","paper_trading_v9_financial_trades.csv")
def f(x):
    try:
        v=float(x); return v if math.isfinite(v) else 0.0
    except: return 0.0
def main():
    print("="*100)
    print("CRYPTO RADAR - PAPER TRADING V9.8 -- RELATÓRIO FINANCEIRO V9")
    print("="*100)
    if not os.path.exists(LEDGER): print("Ledger inexistente."); return
    with open(LEDGER,newline="",encoding="utf-8") as h: rows=list(csv.DictReader(h))
    if not rows:
        print("Trades financeiros V9: 0")
        print("Ainda não há histórico financeiro para avaliar.")
        return
    ret=[f(r["net_return_pct"]) for r in rows]
    pnl=[f(r["net_pnl"]) for r in rows]
    wins=[x for x in ret if x>0]; losses=[x for x in ret if x<0]
    pf=sum(wins)/abs(sum(losses)) if losses else float("inf")
    equity=100.0; peak=100.0; dd=0
    for x in ret:
        equity*=1+x/100; peak=max(peak,equity); dd=min(dd,(equity/peak-1)*100)
    print(f"Trades: {len(rows)}")
    print(f"Win rate: {len(wins)/len(ret)*100:.2f}%")
    print(f"AVG net: {sum(ret)/len(ret):+.4f}%")
    print(f"MED net: {sorted(ret)[len(ret)//2]:+.4f}%")
    print(f"Net P&L: ${sum(pnl):.2f}")
    print(f"Profit Factor: {pf:.3f}")
    print(f"DD sequencial: {dd:.2f}%")
    print("Somente dados financeiros V9; nenhum trade legado V8 é incluído.")
    print("="*100)
if __name__=="__main__": main()
