"""Upload the default Main + Universe page images to the Supabase `page-media`
bucket so they live alongside admin uploads. Idempotent — checks the bucket
first and skips files that already exist.

After this runs, update PAGE_CONTENT_SCHEMA defaults in app.py to use the
returned public URLs (printed at the end of the script).

Usage:
    cd server && python migrations/004_migrate_page_defaults_to_storage.py
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env.local")

from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
    print("Missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY in .env.local", file=sys.stderr)
    sys.exit(1)

c = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
BUCKET = "page-media"

# Defaults referenced by PAGE_CONTENT_SCHEMA in app.py
FILES = [
    {
        "local": ROOT / "assets" / "pictures" / "Jordan Landscape" / "Wadi Rum.webp",
        "storage_path": "defaults/universe-hero-wadi-rum.webp",
        "schema_target": "universe.hero.image",
        "content_type": "image/webp",
    },
    {
        "local": ROOT / "assets" / "pictures" / "Jordan Landscape" / "Maison Henius - universe.webp",
        "storage_path": "defaults/universe-origin-triptych.webp",
        "schema_target": "universe.origin.image",
        "content_type": "image/webp",
    },
    {
        "local": ROOT / "assets" / "pictures" / "Collection & Fragrances" / "beyond-borders-collection.webp",
        "storage_path": "defaults/universe-craft-collection.webp",
        "schema_target": "universe.craft.image",
        "content_type": "image/webp",
    },
    {
        "local": ROOT / "assets" / "pictures" / "Jordan Landscape" / "Story.webp",
        "storage_path": "defaults/main-story-atelier.webp",
        "schema_target": "main.story.image",
        "content_type": "image/webp",
    },
]


def list_existing(bucket: str, prefix: str) -> set[str]:
    try:
        items = c.storage.from_(bucket).list(path=prefix.rstrip("/"))
        return {item["name"] for item in (items or [])}
    except Exception:
        return set()


existing = list_existing(BUCKET, "defaults")

results = []
for f in FILES:
    if not f["local"].is_file():
        print(f"  ! MISSING locally: {f['local']} — skipping")
        continue
    base_name = Path(f["storage_path"]).name
    if base_name in existing:
        print(f"  = already in bucket: {f['storage_path']}")
    else:
        data = f["local"].read_bytes()
        try:
            c.storage.from_(BUCKET).upload(
                f["storage_path"],
                data,
                {
                    "content-type": f["content_type"],
                    "cache-control": "public, max-age=31536000, immutable",
                },
            )
            print(f"  + uploaded {f['storage_path']} ({len(data) // 1024} KB)")
        except Exception as e:
            print(f"  ! FAILED to upload {f['storage_path']}: {e}")
            continue
    url = c.storage.from_(BUCKET).get_public_url(f["storage_path"])
    if isinstance(url, str):
        url = url.rstrip("?")
    results.append((f["schema_target"], url))

print("\n── New default URLs (paste into PAGE_CONTENT_SCHEMA in app.py) ──")
for target, url in results:
    print(f"  {target} → {url}")
