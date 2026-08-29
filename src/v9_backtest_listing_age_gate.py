#!/usr/bin/env python3
"""
CRYPTO RADAR - GATE: BACKTEST HISTÓRICO COM E SEM FILTRO DE IDADE DE LISTAGEM

Reaplica os mesmos 6 critérios de aprovação usados em
v9_historical_backtest.py sobre data/v9_backtest_listing_age.csv,
comparando o resultado com todos os símbolos vs. só os símbolos com
>= MIN_LISTING_AGE_DAYS dias de listagem (mesmo valor já em produção
em scanner_v3.py).

Não busca nada novo na Binance - reusa o CSV já gerado por
v9_backtest_listing_age_analysis.py. Rode aquele script de novo antes
deste se quiser atualizar com histórico mais recente.

Uso:
  python3 src/v9_backtest_listing_age_gate.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from paper_trading_v9_17 import (
    ENTRY_FEE_RATE,
    EXIT_FEE_RATE,
    NOTIONAL,
    SLIPPAGE_ENTRY_PCT,
    SLIPPAGE_EXIT_PCT,
)

ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = ROOT / "data" / "v9_backtest_listing_age.csv"

MIN_LISTING_AGE_DAYS = 90
NEW_LISTING_BUCKET = "< 90 dias (recém-listada)"

# Hipóteses de custo importadas de paper_trading_v9_17.py (não
# duplicadas) - se a V9.17 mudar fee/slippage, este gate acompanha
# automaticamente em vez de silenciosamente usar valores desatualizados.
ROUND_TRIP_COST_PCT = (
    ENTRY_FEE_RATE + EXIT_FEE_RATE + SLIPPAGE_ENTRY_PCT + SLIPPAGE_EXIT_PCT
) * 100.0


def report(name: str, sub: pd.DataFrame) -> bool:
    returns = sub["net_return_pct"]
    wins = returns[returns > 0]
    losses = returns[returns <= 0]
    win_rate = len(wins) / len(returns) * 100.0
    gross_win = wins.sum()
    gross_loss = abs(losses.sum())
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    sub_sorted = sub.sort_values("exit_time")
    equity = 1000.0
    peak = equity
    max_dd = 0.0
    for pnl in sub_sorted["net_pnl"]:
        equity += pnl
        peak = max(peak, equity)
        dd = (equity - peak) / peak * 100.0
        max_dd = min(max_dd, dd)

    mid = len(sub_sorted) // 2
    fh_pnl = sub_sorted.iloc[:mid]["net_pnl"].sum()
    sh_pnl = sub_sorted.iloc[mid:]["net_pnl"].sum()

    stressed_pnl = (
        sub_sorted["net_pnl"] - (ROUND_TRIP_COST_PCT / 100.0) * NOTIONAL
    ).sum()

    print(f"--- {name} (n={len(sub)}) ---")
    print(f"  Retorno médio:   {returns.mean():+.3f}%")
    print(f"  Retorno mediano: {returns.median():+.3f}%")
    print(f"  Win rate:        {win_rate:.1f}%")
    print(f"  Profit factor:   {pf:.2f}")
    print(f"  Max drawdown:    {max_dd:.2f}%")
    print(f"  P&L total:       ${sub['net_pnl'].sum():+.2f}")
    print(f"  1ª metade P&L:   ${fh_pnl:+.2f}   2ª metade P&L: ${sh_pnl:+.2f}")
    print(f"  P&L com custo 2x: ${stressed_pnl:+.2f}")

    checks = {
        "N >= 30 trades": len(sub) >= 30,
        "Mediana positiva": returns.median() > 0,
        "Profit factor >= 1.20": pf >= 1.20,
        "Drawdown > -30%": max_dd > -30.0,
        "1ª e 2ª metade ambas positivas": fh_pnl > 0 and sh_pnl > 0,
        "Sobrevive a custo 2x": stressed_pnl > 0,
    }
    for label, passed in checks.items():
        print(f"  [{'OK' if passed else 'FALHOU'}] {label}")

    approved = all(checks.values())
    print(f"  -> {'APROVADA' if approved else 'NÃO APROVADA'}")
    print()
    return approved


def main() -> int:
    if not INPUT_CSV.exists():
        print(
            f"Arquivo não encontrado: {INPUT_CSV}. "
            "Rode antes: python3 src/v9_backtest_listing_age_analysis.py"
        )
        return 1

    df = pd.read_csv(INPUT_CSV)
    filtered = df[df["age_bucket"] != NEW_LISTING_BUCKET].copy()

    print("=" * 100)
    print("GATE: EFEITO DO FILTRO DE IDADE DE LISTAGEM NO BACKTEST HISTÓRICO")
    print("=" * 100)
    print(f"Total original: {len(df)}   Total com filtro (>= {MIN_LISTING_AGE_DAYS}d): {len(filtered)}")
    print()

    report(f"SEM FILTRO (todas as idades)", df)
    report(f"COM FILTRO (>= {MIN_LISTING_AGE_DAYS} dias de listagem)", filtered)

    print("=" * 100)
    print("O filtro de idade de listagem já está ativo em produção (scanner_v3.py).")
    print("Este script é pra comparar o efeito dele contra o histórico já coletado,")
    print("não substitui reconfirmar com o forward test real acumulando mais trades.")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
