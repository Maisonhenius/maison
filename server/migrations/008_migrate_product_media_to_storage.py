"""Upload every product's local card/bottle/mood/explore image + hero video to
Supabase Storage, then update each products row to use the new public URLs.

After this runs:
  - The admin Product form never shows a bare "card-out-of-control.webp"
    filename — every image/video reference is either a Supabase Storage URL
    or an external URL the admin pasted.
  - Existing legacy filenames are deduplicated: identical files (e.g. video
    1.mp4 used by both Out of Control + Oh My Dear) upload once and both rows
    point at the same Storage URL.

Idempotent — skips files already in the bucket and rows already on a URL.

Usage:
    cd server && python migrations/008_migrate_product_media_to_storage.py
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env.local")

from supabase import create_client

c = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

# Local source directories — these mirror what the Jinja `product_image` filter
# resolves bare filenames to today.
CF_DIR = ROOT / "assets" / "pictures" / "Collection & Fragrances"
VIDEO_DIR = ROOT / "assets" / "videos" / "web"

IMAGE_BUCKET = "product-images"
VIDEO_BUCKET = "page-media"  # already permits video/mp4

# Cache of {local filename: public URL} so duplicates (same video file across
# multiple products) only upload once.
url_cache: dict[str, str] = {}


def list_existing(bucket: str, prefix: str) -> set[str]:
    try:
        items = c.storage.from_(bucket).list(path=prefix.rstrip("/"))
        return {item["name"] for item in (items or []) if isinstance(item, dict)}
    except Exception:
        return set()


def upload(bucket: str, storage_path: str, content_type: str, data: bytes) -> str:
    existing = list_existing(bucket, str(Path(storage_path).parent))
    if Path(storage_path).name not in existing:
        try:
            c.storage.from_(bucket).upload(
                storage_path,
                data,
                {
                    "content-type": content_type,
                    "cache-control": "public, max-age=31536000, immutable",
                },
            )
            print(f"  + uploaded {bucket}/{storage_path} ({len(data) // 1024} KB)")
        except Exception as e:
            print(f"  ! upload failed {bucket}/{storage_path}: {e}")
            raise
    else:
        print(f"  = already in bucket: {bucket}/{storage_path}")
    url = c.storage.from_(bucket).get_public_url(storage_path)
    if isinstance(url, str):
        url = url.rstrip("?")
    return url


def upload_image(slug: str, filename: str) -> str | None:
    """Upload one product image; return its public URL (cached on repeat calls)."""
    if filename in url_cache:
        return url_cache[filename]
    local = CF_DIR / filename
    if not local.is_file():
        print(f"  ! MISSING locally: {local}")
        return None
    url = upload(IMAGE_BUCKET, f"products/{slug}/{filename}", "image/webp", local.read_bytes())
    url_cache[filename] = url
    return url


def upload_video(filename: str) -> str | None:
    """Upload one product video. Same file shared by multiple products → cached."""
    if filename in url_cache:
        return url_cache[filename]
    local = VIDEO_DIR / filename
    if not local.is_file():
        print(f"  ! MISSING locally: {local}")
        return None
    url = upload(VIDEO_BUCKET, f"products/{filename}", "video/mp4", local.read_bytes())
    url_cache[filename] = url
    return url


rows = c.table("products").select("*").order("display_order").execute().data or []
print(f"Products to process: {len(rows)}\n")

IMAGE_FIELDS = ("card_image", "bottle_image", "mood_image", "explore_image")

for p in rows:
    slug = p["id"]
    print(f"── {slug} ──")
    updates: dict[str, str] = {}

    for fld in IMAGE_FIELDS:
        v = (p.get(fld) or "").strip()
        if not v:
            continue
        if v.startswith("http") or v.startswith("/"):
            continue  # already a URL or absolute path — skip
        new_url = upload_image(slug, v)
        if new_url:
            updates[fld] = new_url

    video_field = (p.get("video") or "").strip()
    if video_field and not (video_field.startswith("http") or video_field.startswith("/")):
        new_url = upload_video(video_field)
        if new_url:
            updates["video"] = new_url

    if updates:
        c.table("products").update(updates).eq("id", slug).execute()
        print(f"  ~ updated DB row with {len(updates)} new URLs\n")
    else:
        print("  = nothing to migrate\n")

print("[migrate] done.")
