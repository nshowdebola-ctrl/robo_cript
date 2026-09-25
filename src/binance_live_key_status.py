#!/usr/bin/env python3
"""
CRYPTO RADAR - STATUS DA CHAVE DA API DA BINANCE (live, só leitura)

Imprime um JSON com o que a própria Binance informa sobre a chave em uso
(.binance-live.env): se autentica, permissões (saque, trade spot, leitura),
restrição de IP, data de criação e o IP público atual desta máquina. Usado
pelo portal web/admin.php. Nunca imprime a chave nem o segredo - só os 4
primeiros e 4 últimos caracteres da chave, pra identificar qual está em uso.

Uso:
  python3 src/binance_live_key_status.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from binance_live_executor import ENV_FILE, build_exchange, load_env  # noqa: E402


def main() -> int:
    out: dict = {"checked_at": datetime.now(timezone.utc).isoformat()}
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=8) as resp:
            out["public_ip"] = resp.read().decode().strip()
    except Exception:
        out["public_ip"] = None
    try:
        env = load_env(ENV_FILE)
        key = next((v for k, v in env.items() if "KEY" in k.upper() and "SECRET" not in k.upper()), "")
        out["key_hint"] = f"{key[:4]}…{key[-4:]}" if len(key) >= 8 else None
        ex = build_exchange(env)
        r = ex.sapi_get_account_apirestrictions()
        out.update({
            "ok": True,
            "ip_restrict": bool(r.get("ipRestrict")),
            "enable_withdrawals": bool(r.get("enableWithdrawals")),
            "enable_spot_trading": bool(r.get("enableSpotAndMarginTrading")),
            "enable_reading": bool(r.get("enableReading")),
            "enable_internal_transfer": bool(r.get("enableInternalTransfer")),
            "enable_futures": bool(r.get("enableFutures")),
            "created_at": (
                datetime.fromtimestamp(int(r["createTime"]) / 1000, timezone.utc).isoformat()
                if r.get("createTime") else None
            ),
        })
    except Exception as exc:
        out.update({"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
