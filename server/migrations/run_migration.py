"""Run a SQL migration file against DATABASE_URL.

Usage:
    cd server && python migrations/run_migration.py 001_products_and_content.sql
"""
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env.local")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("DATABASE_URL not set in .env.local", file=sys.stderr)
    sys.exit(1)

if len(sys.argv) < 2:
    print("usage: run_migration.py <filename.sql>", file=sys.stderr)
    sys.exit(1)

filename = sys.argv[1]
sql_path = Path(__file__).resolve().parent / filename
if not sql_path.is_file():
    print(f"migration file not found: {sql_path}", file=sys.stderr)
    sys.exit(1)

sql = sql_path.read_text()
print(f"[migrate] applying {filename} ({len(sql)} bytes)...")

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
try:
    with conn.cursor() as cur:
        cur.execute(sql)
    print(f"[migrate] ✓ {filename} applied")
finally:
    conn.close()
