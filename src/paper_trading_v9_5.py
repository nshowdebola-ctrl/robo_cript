#!/usr/bin/env python3
import csv, os, math

BASE=os.path.abspath(os.path.join(os.path.dirname(__file__),".."))
LEDGER=os.path.join(BASE,"data","paper_trading_v9_financial_trades.csv")
REPORT=os.path.join(BASE,"data","paper_trading_v9_5_report.csv")

def n(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else 0.0
    except:
        return 0.0

def main():
    print("="*100)
    print("CRYPTO RADAR - PAPER TRADING V9.5 -- RELATÓRIO FINANCEIRO")
    print("="*100)
    if not os.path.exists(LEDGER):
        raise SystemExit(f"Ledger não encontrado: {LEDGER}")
    with open(LEDGER,newline="",encoding="utf-8") as fh:
        rows=list(csv.DictReader(fh))

    if not rows:
        print("Ledger financeiro V9 vazio.")
        print("Nenhuma métrica financeira é calculada até existirem operações V9.")
        print("CSV legado V8 não é usado.")
        return

    r=[n(x["net_return_pct"]) for x in rows]
    wins=[x for x in r if x>0]; losses=[x for x in r if x<0]
    avg=sum(r)/len(r)
    s=sorted(r); m=len(s)
    med=s[m//2] if m%2 else (s[m//2-1]+s[m//2])/2
    pf=sum(wins)/abs(sum(losses)) if losses else float("inf")
    wr=len(wins)/m*100

    # Drawdown sobre sequência de trades V9, sem usar V8.
    equity=100.0; peak=100.0; dd=0.0
    for x in r:
        equity *= (1+x/100)
        peak=max(peak,equity)
        dd=min(dd,(equity/peak-1)*100)

    print(f"Trades: {m}")
    print(f"Win rate: {wr:.2f}%")
    print(f"AVG net: {avg:+.4f}%")
    print(f"MED net: {med:+.4f}%")
    print(f"Profit Factor: {pf:.3f}")
    print(f"DD sequencial V9: {dd:.2f}%")
    print("IMPORTANTE: métricas calculadas somente sobre o ledger financeiro V9.")

    with open(REPORT,"w",newline="",encoding="utf-8") as fh:
        w=csv.writer(fh)
        w.writerow(["metric","value"])
        w.writerow(["trades",m]); w.writerow(["win_rate_pct",wr])
        w.writerow(["avg_net_return_pct",avg]); w.writerow(["median_net_return_pct",med])
        w.writerow(["profit_factor",pf]); w.writerow(["sequential_drawdown_pct",dd])
    print(f"Arquivo: {REPORT}")
    print("="*100)

if __name__=="__main__":
    main()
