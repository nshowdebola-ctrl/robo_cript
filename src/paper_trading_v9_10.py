#!/usr/bin/env python3
"""Crypto Radar V9.10: financial closing layer."""
import os,sys
sys.path.insert(0,os.path.dirname(__file__))
from paper_trading_v9_9 import open_trade,close_trade
def main():
    print("="*100); print("CRYPTO RADAR - PAPER TRADING V9.10 -- FECHAMENTO FINANCEIRO"); print("="*100)
    print("Nenhuma operação é criada sem entrada explícita da estratégia."); print("Fees, slippage e P&L são calculados no fechamento."); print("Modo: PAPER ONLY"); print("Ordens reais: NÃO"); print("="*100)
if __name__=="__main__": main()
