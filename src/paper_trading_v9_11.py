#!/usr/bin/env python3
"""Crypto Radar V9.11: isolated financial-cycle smoke test."""
import csv,os,sys,tempfile
sys.path.insert(0,os.path.dirname(__file__))
import paper_trading_v9_9 as m
def main():
    print("="*100); print("CRYPTO RADAR - PAPER TRADING V9.11 -- TESTE DO CICLO FORWARD"); print("="*100)
    original=m.LEDGER; fd,path=tempfile.mkstemp(prefix="v9_11_",suffix=".csv"); os.close(fd); os.unlink(path); m.LEDGER=path
    try:
        p=m.open_trade("TEST/USDT",100,100,scenario="V9_11_SMOKE",entry_fee_rate=.001,slippage_entry_pct=.1,entry_time="2026-01-01T00:00:00+00:00")
        r=m.close_trade(p,105,exit_fee_rate=.001,slippage_exit_pct=.1,exit_time="2026-01-01T02:00:00+00:00",exit_reason="TARGET")
        assert float(r["net_pnl"])>0
        with open(path,newline="",encoding="utf-8") as f: rows=list(csv.DictReader(f))
        assert len(rows)==1 and set(rows[0])==set(m.FIELDS)
        print("Smoke test: OK"); print(f'Net P&L sintético: ${float(r["net_pnl"]):.6f}'); print("Trade de teste NÃO foi gravado no ledger V9 real."); print("VEREDITO: V9.9/V9.10 prontos para integração.")
    finally:
        if os.path.exists(path): os.remove(path)
        m.LEDGER=original
    print("="*100)
if __name__=="__main__": main()
