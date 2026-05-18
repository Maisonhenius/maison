"""Upload Main page hero video + about image + scroll cinematic to
Supabase Storage (page-media bucket) so the admin Content editor for
the Main page shows real URLs and never local /static/ paths.

Idempotent — skips files already present.

Usage:
    cd server && python migrations/005_migrate_main_page_media_to_storage.py
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

FILES = [
    {
        "local": ROOT / "assets" / "videos" / "web" / "brand-film-silent.mp4",
        "storage_path": "defaults/main-hero-brand-film.mp4",
        "schema_target": "main.hero.video",
        "content_type": "video/mp4",
    },
    {
        "local": ROOT / "assets" / "pictures" / "Jordan Landscape" / "Wadi Rum.webp",
        "storage_path": "defaults/main-about-wadi-rum.webp",
        "schema_target": "main.about.image",
        "content_type": "image/webp",
    },
    {
        "local": ROOT / "assets" / "videos" / "web" / "scroll-cinematic.mp4",
        "storage_path": "defaults/main-scroll-cinematic.mp4",
        "schema_target": "main.cinematic.video",
        "content_type": "video/mp4",
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
