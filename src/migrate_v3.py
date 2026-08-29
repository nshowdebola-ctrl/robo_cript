import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "crypto_radar.db"


def main():
    print("=" * 80)
    print("MIGRAÇÃO COMPLETA - SCANNER V3")
    print("=" * 80)
    print(f"Banco: {DB_PATH}")

    if not DB_PATH.exists():
        print("\nERRO: banco não encontrado.")
        return

    conn = sqlite3.connect(DB_PATH)

    # Verifica se a tabela existe
    table = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
          AND name='scanner_v3_results'
        """
    ).fetchone()

    if table is None:
        print("\nA tabela scanner_v3_results não existe.")
        print("Ela será criada pelo scanner_v3.py.")
        conn.close()
        return

    # Todas as colunas que o V3 atual pode utilizar.
    #
    # SQLite permite adicionar colunas novas sem apagar
    # os registros antigos.
    columns = {
        "timestamp": "TEXT",
        "symbol": "TEXT",
        "price": "REAL",
        "score": "INTEGER DEFAULT 0",

        "rsi": "REAL DEFAULT 0",
        "rsi_points": "REAL DEFAULT 0",

        "trend_1h": "REAL DEFAULT 0",
        "trend_4h": "REAL DEFAULT 0",

        "trend_1h_points": "REAL DEFAULT 0",
        "trend_4h_points": "REAL DEFAULT 0",

        "momentum": "REAL DEFAULT 0",
        "momentum_points": "REAL DEFAULT 0",

        "volume": "REAL DEFAULT 0",
        "volume_points": "REAL DEFAULT 0",

        "relative_volume": "REAL DEFAULT 0",
        "volume_relative": "REAL DEFAULT 0",

        "atr": "REAL DEFAULT 0",
        "atr_percent": "REAL DEFAULT 0",

        "confidence": "INTEGER DEFAULT 0",

        "classification": "TEXT DEFAULT ''",
        "signal": "TEXT DEFAULT ''",

        "risk_flags": "TEXT DEFAULT ''",
    }

    existing = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(scanner_v3_results)"
        )
    }

    print("\nVerificando estrutura da tabela...\n")

    added = 0
    already = 0

    for column, definition in columns.items():

        if column in existing:
            print(f"  ✓ {column}")
            already += 1
            continue

        try:
            conn.execute(
                f"""
                ALTER TABLE scanner_v3_results
                ADD COLUMN {column} {definition}
                """
            )

            print(f"  + {column} ADICIONADA")
            added += 1

        except sqlite3.Error as exc:
            print(f"  ✗ Erro adicionando {column}: {exc}")

    conn.commit()

    print("\n" + "=" * 80)
    print("ESTRUTURA FINAL")
    print("=" * 80)

    rows = conn.execute(
        "PRAGMA table_info(scanner_v3_results)"
    ).fetchall()

    for row in rows:
        print(f"{row[1]:30} {row[2]}")

    count = conn.execute(
        "SELECT COUNT(*) FROM scanner_v3_results"
    ).fetchone()[0]

    conn.close()

    print("\n" + "=" * 80)
    print("RESULTADO DA MIGRAÇÃO")
    print("=" * 80)
    print(f"Colunas já existentes: {already}")
    print(f"Colunas adicionadas:   {added}")
    print(f"Registros preservados: {count}")
    print("=" * 80)

    print("\n✓ Migração concluída.")
    print("Agora execute:")
    print("  python src/scanner_v3.py")


if __name__ == "__main__":
    main()
