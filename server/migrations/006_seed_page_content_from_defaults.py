"""Seed the page_content table with every field in PAGE_CONTENT_SCHEMA so the
admin Content editor always loads with real, live content — no more
"default vs customized" UX, just one source of truth in the DB.

Idempotent — only inserts rows that don't exist yet; never overwrites an
existing customization.

Usage:
    cd server && python migrations/006_seed_page_content_from_defaults.py
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env.local")

# Import the live schema so the seed never drifts from the source of truth.
sys.path.insert(0, str(ROOT / "server"))
import app as _app

from supabase import create_client

c = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

inserted = skipped = 0
for page, entries in _app.PAGE_CONTENT_SCHEMA.items():
    # What's already in the table?
    existing = c.table("page_content").select("section,field").eq("page", page).execute()
    existing_keys = {(b["section"], b["field"]) for b in (existing.data or [])}
    rows_to_insert = []
    for i, entry in enumerate(entries):
        key = (entry["section"], entry["field"])
        if key in existing_keys:
            skipped += 1
            continue
        rows_to_insert.append({
            "page": page,
            "section": entry["section"],
            "field": entry["field"],
            "field_type": entry["type"],
            "value": entry.get("default", ""),
            "display_order": i,
        })
    if rows_to_insert:
        c.table("page_content").insert(rows_to_insert).execute()
        inserted += len(rows_to_insert)
        print(f"  + {page}: inserted {len(rows_to_insert)} rows")
    else:
        print(f"  = {page}: already fully seeded")

print(f"\n[seed] inserted {inserted} rows, skipped {skipped} (already existed)")
