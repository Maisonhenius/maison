"""Backfill any page_content rows whose `value` is empty with the schema
default. Earlier admin saves stored empty strings as a "track-the-default"
signal, but the new single-source-of-truth UX shows whatever is in the DB
verbatim — empty rows would look like blank fields to the admin.

Only touches rows where value is '' (or NULL). Never overwrites an existing
non-empty value.

Usage:
    cd server && python migrations/007_backfill_empty_page_content.py
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env.local")

# Import live schema
sys.path.insert(0, str(ROOT / "server"))
import app as _app

from supabase import create_client

c = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

# Build a lookup keyed by (page, section, field) → default string
defaults = {}
for page, entries in _app.PAGE_CONTENT_SCHEMA.items():
    for entry in entries:
        defaults[(page, entry["section"], entry["field"])] = entry.get("default", "")

updated = 0
skipped = 0
for (page, section, field), default_value in defaults.items():
    if not default_value:
        continue  # nothing to write
    # Fetch the existing row
    existing = (
        c.table("page_content")
        .select("id,value")
        .eq("page", page)
        .eq("section", section)
        .eq("field", field)
        .execute()
    )
    rows = existing.data or []
    if not rows:
        # Row missing entirely — insert fresh
        c.table("page_content").insert({
            "page": page,
            "section": section,
            "field": field,
            "field_type": next(
                (e["type"] for e in _app.PAGE_CONTENT_SCHEMA[page]
                 if e["section"] == section and e["field"] == field),
                "text",
            ),
            "value": default_value,
            "display_order": 0,
        }).execute()
        print(f"  + inserted {page}.{section}.{field}")
        updated += 1
        continue
    row = rows[0]
    if row.get("value"):
        skipped += 1
        continue
    # Empty — backfill
    c.table("page_content").update({"value": default_value}).eq("id", row["id"]).execute()
    print(f"  ~ backfilled {page}.{section}.{field} (len={len(default_value)})")
    updated += 1

print(f"\n[backfill] updated/inserted {updated}, skipped {skipped} (already had a value)")
