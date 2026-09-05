#!/usr/bin/env python3
"""
CRYPTO RADAR - REATIVAR CIRCUIT BREAKER (live trading)

Wrapper fino de CLI pra `clear_breaker()` - permite o portal
(web/live.php) chamar via `exec()` do mesmo jeito que já chama
binance_live_reset.py, sem embutir lógica Python em string PHP.

Ação manual explícita apenas - nunca chamado automaticamente por
nenhum ciclo do trader/loop.

Uso:
    python3 src/binance_live_circuit_breaker_clear.py [origem]
"""

from __future__ import annotations

import sys

from binance_live_circuit_breaker import clear_breaker


def main() -> int:
    cleared_by = sys.argv[1] if len(sys.argv) > 1 else "cli"
    state = clear_breaker(cleared_by=cleared_by)
    print(f"Circuit breaker reativado (cleared_by={state['cleared_by']}, cleared_at={state['cleared_at']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
