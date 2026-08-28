from pathlib import Path

p = Path(__file__).with_name('main.py')
s = p.read_text(encoding='utf-8')
old = '''    # Supabase Postgres is provisioned separately through the project migration.\n    # Skip the SQLite schema/seed routine when DATABASE_URL is configured.\n    if DATABASE_URL:\n        conn = get_db()\n        conn.close()\n        return\n\n    conn = get_db()'''
new = '''    # Production uses Supabase PostgreSQL whenever DATABASE_URL is configured.\n    # Run the same schema + seed routine against PostgreSQL so the SCMS is fully\n    # persistent in production. SQLite remains available for local development.\n    conn = get_db()'''
if old in s:
    s = s.replace(old, new)
old2 = '''def execute_script(conn: sqlite3.Connection, sql: str) -> None:\n    conn.executescript(sql)'''
new2 = '''def execute_script(conn, sql: str) -> None:\n    # Both database adapters expose executescript; PostgreSQL adapter translates\n    # SQLite AUTOINCREMENT and executes statements individually.\n    conn.executescript(sql)'''
if old2 in s:
    s = s.replace(old2, new2)
old3 = '''def add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:\n    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}\n    if column not in cols:\n        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")'''
new3 = '''def add_column_if_missing(conn, table: str, column: str, definition: str) -> None:\n    if DATABASE_URL:\n        row = conn.execute(\n            "SELECT 1 FROM information_schema.columns WHERE table_name=? AND column_name=?",\n            (table, column),\n        ).fetchone()\n        if not row:\n            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")\n        return\n    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}\n    if column not in cols:\n        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")'''
if old3 in s:
    s = s.replace(old3, new3)
p.write_text(s, encoding='utf-8')
