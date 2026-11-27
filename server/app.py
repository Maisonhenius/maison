from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse, Response
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pathlib import Path
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from typing import Optional
import asyncio
import base64
import os
import re
import json
import time
import uuid
from urllib.parse import quote
from markupsafe import Markup, escape
import mimetypes
import traceback
from stripe import StripeClient, Webhook, SignatureVerificationError
import email_service

# --- Async DB helpers ---
#
# supabase-py is a SYNC library. Calling `.execute()` inside an `async def` route
# blocks the asyncio event loop for the duration of the network round-trip to
# Supabase (~100–400ms each), meaning no other requests can be served during
# that time. Wrapping every call in `asyncio.to_thread` runs the blocking I/O on
# a worker thread and frees the event loop to handle concurrent requests.
#
# Pattern at every call site: `await _db(supabase.table("...").select("*"))`
# instead of `supabase.table("...").select("*").execute()`.


async def _db(query):
    """Run a Supabase query builder's `.execute()` in a worker thread."""
    return await asyncio.to_thread(query.execute)


async def _to_thread(callable_, *args, **kwargs):
    """Convenience: run any blocking callable in a worker thread."""
    return await asyncio.to_thread(callable_, *args, **kwargs)

# Register WebP MIME type — Starlette uses Python's mimetypes module via
# StaticFiles, and the default registry on Linux/Alpine often misses image/webp
# (was being served as text/plain). Must run BEFORE any StaticFiles mount.
mimetypes.add_type("image/webp", ".webp")

# Register M4A audio MIME type. The Python default emits "audio/mp4a-latm"
# (a low-overhead-AAC subtype) which Safari and Chrome accept but is not the
# spec-blessed type. "audio/mp4" is the standard for AAC-in-MP4-container.
# Used by the hero <audio> element pointing at brand-film-audio.m4a.
mimetypes.add_type("audio/mp4", ".m4a")

# Load environment variables
load_dotenv(Path(__file__).resolve().parent.parent / '.env.local')

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

# Supabase clients
from supabase import create_client
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)       # Service role (DB + admin ops)
supabase_anon = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)          # Anon (auth flows + email sending)

# Stripe
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
stripe_client = StripeClient(STRIPE_SECRET_KEY) if STRIPE_SECRET_KEY else None

# Allowed emails for admin magic link login
ALLOWED_EMAILS = ["husein.aldarawish@gmail.com"]  # sole owner since 2026-11-27 (owner request: second address removed)

# --- Admin upload constraints ---
# Two Supabase Storage buckets gated by the admin endpoints below:
#   product-images: hero / card / mood / bottle / ingredient images
#   page-media:     editable CMS images + short videos for Main + Universe pages
ALLOWED_BUCKETS = {"product-images", "page-media"}
ALLOWED_IMAGE_TYPES = {"image/webp", "image/jpeg", "image/png"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/webm"}
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB hard ceiling — matches bucket policy

# --- Pre-launch gate ---
# While True, the /checkout "Continue to Payment" button shows a branded
# "arriving soon" modal instead of redirecting to Stripe, and create-session
# refuses to start a payment. Flip to False (and redeploy) to enable real
# checkout for the official launch. Single source of truth for the gate.
CHECKOUT_COMING_SOON = True

app = FastAPI(title="Maison Henius")


# --- Performance middleware ---
#
# Two layers:
# 1. CacheControlMiddleware (inner) tags static asset responses with long
#    Cache-Control headers so Railway's Fastly edge starts caching them.
#    Without this, every request hits the origin in europe-west4 (~600ms TTFB)
#    instead of the nearest Fastly PoP (~30ms). HTML responses get NO cache
#    header so dynamic content stays fresh.
# 2. GZipMiddleware (outer) compresses HTML/CSS/JS/JSON. ~70% reduction on
#    text payloads. Skips already-compressed content (images, video, music)
#    automatically.
#
# Order matters: middleware added LAST runs OUTERMOST. GZip must wrap
# CacheControl so the Vary: Accept-Encoding header lands AFTER cache-control.

class CacheControlMiddleware(BaseHTTPMiddleware):
    """Add Cache-Control headers based on path so Fastly + browsers can cache.

    Strategy:
    - /static/css/*, /static/js/*, /static/admin/*: cache-busted via ?v=N in
      template references → safe to cache forever (immutable).
    - /static/assets/*: rarely change (product images, hero videos, scroll
      frames, music) → 30 days.
    - HTML pages and API responses: no cache header (default = no edge cache,
      always fresh from origin).
    """
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if response.headers.get("cache-control"):
            return response
        # Never apply long-lived cache headers to error responses. A 404 today
        # might be a valid asset tomorrow (e.g. frames added after first visit)
        # and the client must re-request, not serve a stale 404 from cache.
        if not 200 <= response.status_code < 300:
            return response
        path = request.url.path
        if path.startswith(("/static/css/", "/static/js/", "/static/admin/")):
            response.headers["cache-control"] = "public, max-age=31536000, immutable"
        elif path.startswith("/static/assets/"):
            response.headers["cache-control"] = "public, max-age=2592000"
        elif path.startswith("/static/"):
            # Root static files (favicon, robots.txt) — short cache
            response.headers["cache-control"] = "public, max-age=86400"
        return response


app.add_middleware(CacheControlMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=500)


async def get_admin_user(request: Request) -> Optional[object]:
    """Owner/admin only. Every /api/admin/* endpoint calls this, so warehouse
    (fulfilment) accounts are refused everywhere by default — and the attempt is
    logged. Roles are resolved in _resolve_staff() (Team access section below)."""
    staff = await _resolve_staff(request)
    if staff and staff.role in ("owner", "admin"):
        return staff.user
    if staff:
        await _log_staff(staff, "denied", f"{request.method} {request.url.path}", request)
    return None


async def get_authenticated_user(request: Request):
    """Extract and validate user from Bearer token"""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ")[1]
    try:
        user_resp = await _to_thread(supabase.auth.get_user, token)
        if user_resp and user_resp.user:
            return user_resp.user
    except Exception:
        pass
    return None


# Paths
BASE_DIR = Path(__file__).resolve().parent.parent  # /Users/.../maison
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Static files - mount only specific directories (never expose project root)
app.mount("/static/css", StaticFiles(directory=BASE_DIR / "css"), name="static-css")
app.mount("/static/js", StaticFiles(directory=BASE_DIR / "js"), name="static-js")
app.mount("/static/assets", StaticFiles(directory=BASE_DIR / "assets"), name="static-assets")
app.mount("/static/admin", StaticFiles(directory=BASE_DIR / "admin"), name="static-admin")

ALLOWED_ROOT_STATIC = {"favicon.ico", "favicon-32x32.png", "apple-touch-icon.png", "robots.txt"}

@app.get("/static/{filename:path}")
async def root_static_files(filename: str):
    if filename in ALLOWED_ROOT_STATIC:
        file_path = BASE_DIR / filename
        if file_path.is_file():
            return FileResponse(file_path)
    return JSONResponse({"error": "Not found"}, status_code=404)

# Canonical public address. Used for social-share previews (og:url / og:image),
# the canonical link and the sitemap, so shares never show the railway.app host.
SITE_URL = "https://www.maisonhenius.com"


# Search engines look for these two files at the site root, not under /static.
@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    return FileResponse(BASE_DIR / "robots.txt", media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml():
    paths = ["/", "/shop", "/story", "/journal", "/terms", "/privacy"]
    paths += [f"/products/{quote(slug)}" for slug in get_products_dict()]
    urls = "".join(f"<url><loc>{SITE_URL}{p}</loc></url>" for p in paths)
    # Journal articles, with their last-changed date so Google re-crawls edits.
    for post in await journal_live_posts():
        lastmod = (post.get("updated_iso") or "")[:10]
        lm = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
        urls += f"<url><loc>{SITE_URL}/journal/{quote(post['slug'])}</loc>{lm}</url>"
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')
    return Response(content=xml, media_type="application/xml")


# Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["site_url"] = SITE_URL
# Website translation (Weglot). Empty = feature off; set the public API key from
# the Weglot dashboard in Railway's environment variables to turn it on.
templates.env.globals["weglot_api_key"] = os.environ.get("WEGLOT_API_KEY", "")


# --- Image URL resolution filters ---
# Image fields in the products + page_content tables can hold EITHER:
#   1. a legacy filename (`card-out-of-control.webp`) → prepend static path
#   2. an absolute path (`/static/...`) → use as-is
#   3. an absolute URL (`https://...supabase.co/storage/v1/...`) from admin upload
# Filters resolve all three to a browser-fetchable URL. Templates use:
#   <img src="{{ product.card_image | product_image }}">
#   <img src="{{ img | ingredient_image }}">
#   <img src="{{ value | page_media }}">

def _resolve_url(value: str, static_prefix: str, default_ext: str = "") -> str:
    if not value:
        return ""
    if value.startswith(("http://", "https://", "/")):
        return value
    # Legacy bare filename — prepend the known static directory.
    if default_ext and not value.endswith(default_ext):
        value = f"{value}{default_ext}"
    return f"{static_prefix}{value}"


def jinja_product_image(value: str) -> str:
    return _resolve_url(value, "/static/assets/pictures/Collection & Fragrances/")


def jinja_ingredient_image(value: str) -> str:
    # Ingredients are stored as bare slugs (e.g. "lemon") with no extension.
    return _resolve_url(value, "/static/assets/pictures/ingredients/", default_ext=".webp")


def jinja_product_video(value: str) -> str:
    # Legacy bare filenames (e.g. "1.mp4") resolve into /static/assets/videos/web/;
    # full URLs (after the Supabase Storage migration) pass through unchanged.
    return _resolve_url(value, "/static/assets/videos/web/")


def jinja_page_media(value: str) -> str:
    return _resolve_url(value, "/static/assets/")


templates.env.filters["product_image"] = jinja_product_image
templates.env.filters["ingredient_image"] = jinja_ingredient_image
templates.env.filters["product_video"] = jinja_product_video
templates.env.filters["page_media"] = jinja_page_media


# A paragraph may start with a short label between dashes, e.g.
# "- The House - From the lush gardens…". `lead_label` renders that label in a
# <span class="lead-label"> so it can be styled like a heading; the rest of the
# text is unchanged. Text without such a label is returned as-is (escaped).
_LEAD_LABEL_RE = re.compile(r"^\s*([-–—])\s*([^-–—\n]{1,40}?)\s*[-–—]\s*(.*)$", re.S)


def jinja_lead_label(value: str) -> Markup:
    text = value or ""
    m = _LEAD_LABEL_RE.match(text)
    if not m:
        return escape(text)
    return Markup('<span class="lead-label">{}</span> {}').format(f"- {m.group(2)} -", m.group(3))


templates.env.filters["lead_label"] = jinja_lead_label


def is_video_url(value: str) -> bool:
    """True if a media URL points to a video (by file extension). Lets the single
    product hero field render a <video> vs an <img> from one stored URL."""
    if not value:
        return False
    path = value.split("?")[0].split("#")[0].lower()
    return path.endswith((".mp4", ".webm", ".mov", ".m4v"))


templates.env.globals["is_video_url"] = is_video_url


# Product catalog — loaded from Supabase `products` table at app startup and
# cached in-memory. Admin mutations call `reload_products_cache()` to invalidate.
# Use the get_product()/get_products_dict() helpers — never read _PRODUCTS_CACHE
# directly so we can swap caching strategies later without rewriting every call.

_PRODUCTS_CACHE: dict = {}

# JSON-able product fields the public site + cart + checkout rely on.
PRODUCT_FIELDS = (
    "slug", "name", "family", "price", "mood", "character", "description",
    "wearer", "notes", "card_image", "mood_image", "explore_image",
    "bottle_image", "video", "is_hidden", "display_order",
)


# Products shown as "Coming Soon" (instead of "Out of Stock") everywhere on the
# public site, by slug. They can't be bought while listed here, whatever their
# stock. Remove a slug (and redeploy) when that product launches.
COMING_SOON_SLUGS = {"discovery-collection"}

# Products whose price is never shown on the public site, and whose Price field
# is optional in the admin form (owner request: the Discovery Collection only).
# Leaving Price empty in admin keeps the stored price unchanged.
NO_PRICE_SLUGS = {"discovery-collection"}


def _row_to_product(row: dict) -> dict:
    """Normalize a Supabase products row to the dict shape templates + routes expect.

    Price is converted to float (DB returns Decimal; Stripe + JS want a plain number).
    JSONB columns (`wearer`, `notes`) come back as native Python list/dict already.
    """
    return {
        "slug": row.get("slug") or row.get("id", ""),
        "name": row.get("name", ""),
        "family": row.get("family", ""),
        "price": float(row.get("price") or 0),
        "mood": row.get("mood", ""),
        "character": row.get("character", ""),
        "description": row.get("description", ""),
        "wearer": row.get("wearer") or [],
        "notes": row.get("notes") or {},
        "card_image": row.get("card_image", ""),
        "mood_image": row.get("mood_image", ""),
        "explore_image": row.get("explore_image", ""),
        "bottle_image": row.get("bottle_image", ""),
        # `video` is the single hero-media field — holds an image OR a video URL;
        # the product page renders <img> or <video> based on the file extension.
        "video": row.get("video", ""),
        # Per-product editable copy (migration 012). Each field is NOT NULL with a
        # column-level DEFAULT in the DB, so these `or "..."` fallbacks only
        # fire if the migration hasn't been applied yet.
        "essence_label": row.get("essence_label") or "The Essence",
        "essence_tagline": row.get("essence_tagline") or "Our Essence does not seek to impress.\n\nIt seeks to resonate.",
        "wearer_label": row.get("wearer_label") or "The Wearer",
        "composition_label": row.get("composition_label") or "The Composition",
        "composition_subtitle": row.get("composition_subtitle") or "A journey in three acts",
        "bottle_label": row.get("bottle_label") or "The Bottle",
        "bottle_size": row.get("bottle_size") or "Eau de Parfum · 100ml",
        "bottle_description": row.get("bottle_description") or "Custom golden Zamac cap inspired by ancient Ionic columns. Amber glass with deep-to-golden gradient. Brass label plate with embossed detailing.",
        "is_hidden": bool(row.get("is_hidden", False)),
        "display_order": int(row.get("display_order") or 0),
        "stock": int(row.get("stock") or 0),
        # Warehouse reference code (migration 014). Empty until the owner sets it;
        # the fulfilment pages fall back to the product slug.
        "sku": row.get("sku") or "",
        # Price hidden on the public site (see NO_PRICE_SLUGS).
        "show_price": (row.get("slug") or row.get("id", "")) not in NO_PRICE_SLUGS,
        # Not yet launched: badge + buttons say "Coming Soon" instead of "Out of Stock".
        "coming_soon": (row.get("slug") or row.get("id", "")) in COMING_SOON_SLUGS,
        # Derived boolean for templates — the raw count never reaches the customer.
        # Coming-soon products are never purchasable.
        "in_stock": int(row.get("stock") or 0) > 0 and (row.get("slug") or row.get("id", "")) not in COMING_SOON_SLUGS,
        "created_at": row.get("created_at", ""),
    }


async def reload_products_cache() -> None:
    """Refresh in-memory products cache from DB. Call after any admin mutation."""
    global _PRODUCTS_CACHE
    result = await _db(
        supabase.table("products").select("*").order("display_order")
    )
    _PRODUCTS_CACHE = {row["id"]: _row_to_product(row) for row in (result.data or [])}


def get_product(product_id: str, *, include_hidden: bool = False) -> Optional[dict]:
    """Look up one product by id (slug). Hidden products are filtered for public callers."""
    p = _PRODUCTS_CACHE.get(product_id)
    if p is None:
        return None
    if not include_hidden and p["is_hidden"]:
        return None
    return p


def get_products_dict(*, include_hidden: bool = False) -> dict:
    """Return all products as {slug: product} dict, in display_order. Same shape as old PRODUCTS."""
    if include_hidden:
        return dict(_PRODUCTS_CACHE)
    return {k: v for k, v in _PRODUCTS_CACHE.items() if not v["is_hidden"]}


@app.on_event("startup")
async def _load_products_on_startup():
    """Populate the products + footer-social caches before serving traffic."""
    try:
        await reload_products_cache()
        print(f"[startup] Loaded {len(_PRODUCTS_CACHE)} products from DB")
    except Exception as e:
        # Never let a transient Supabase blip block server boot — log and continue
        # with an empty cache. Routes that depend on products will 404 until next reload.
        print(f"[startup] FAILED to load products: {e}")
    try:
        await reload_footer_social()
    except Exception as e:
        # Cache is already seeded with schema defaults at import, so the footer
        # still shows Instagram/TikTok even if this DB read fails.
        print(f"[startup] FAILED to load footer social: {e}")


# --- Shared template context ---

def get_context():
    return {
        "supabase_url": SUPABASE_URL,
        "supabase_anon_key": SUPABASE_ANON_KEY,
    }

# --- Page Routes ---

# How many products the landing page's "The Collection" section shows.
LANDING_PRODUCT_COUNT = 6


def is_product_set(p: dict) -> bool:
    """Sets/coffrets (family "Collection", e.g. the Discovery Collection) are
    listed after single fragrances on the homepage and in the shop (owner request)."""
    return (p.get("family") or "").strip().lower() == "collection"


templates.env.globals["is_product_set"] = is_product_set


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    content_map = await load_page_content("main")
    # Landing "The Collection" section shows LANDING_PRODUCT_COUNT visible
    # products: single fragrances first (newest first, by created_at), then
    # sets/coffrets (family "Collection", e.g. the Discovery Collection) last.
    # Hidden products (admin toggle) are excluded by get_products_dict().
    # Any beyond the count live on /shop only.
    all_visible = list(get_products_dict().values())
    all_visible.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    all_visible.sort(key=is_product_set)  # stable: keeps newest-first within each group
    landing_products = all_visible[:LANDING_PRODUCT_COUNT]
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            **get_context(),
            "products": get_products_dict(),
            "landing_products": landing_products,
            "content": _make_content_helper(content_map),
        },
    )

@app.get("/products", response_class=HTMLResponse)
@app.get("/products/", response_class=HTMLResponse)
async def products_index():
    return RedirectResponse("/shop", status_code=302)


@app.get("/shop", response_class=HTMLResponse)
async def shop(request: Request):
    """E-commerce grid showing all visible products with a sort control.
    No family filter row (removed at the owner's request). Default ("Featured")
    order is display_order with sets (Discovery Collection) moved last; the
    page's sort script keeps sets last for every option except "Newest first"."""
    products = dict(sorted(get_products_dict().items(), key=lambda kv: is_product_set(kv[1])))  # stable
    return templates.TemplateResponse(
        request=request,
        name="shop.html",
        context={**get_context(), "products": products},
    )

@app.get("/products/{slug}", response_class=HTMLResponse)
async def product_detail(request: Request, slug: str):
    product = get_product(slug)
    if not product:
        return HTMLResponse("Product not found", status_code=404)
    others = {k: v for k, v in get_products_dict().items() if k != slug}
    return templates.TemplateResponse(request=request, name="products/detail.html", context={**get_context(), "product": product, "others": others})

@app.get("/story", response_class=HTMLResponse)
async def story(request: Request):
    content_map = await load_page_content("universe")
    return templates.TemplateResponse(
        request=request,
        name="story.html",
        context={
            **get_context(),
            "content": _make_content_helper(content_map),
        },
    )

@app.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return templates.TemplateResponse(request=request, name="terms.html", context=get_context())

@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return templates.TemplateResponse(request=request, name="privacy.html", context=get_context())

@app.get("/cart", response_class=HTMLResponse)
async def cart(request: Request):
    return templates.TemplateResponse(request=request, name="cart.html", context=get_context())

@app.get("/checkout", response_class=HTMLResponse)
async def checkout(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="checkout.html",
        context={**get_context(), "coming_soon": CHECKOUT_COMING_SOON},
    )

@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context=get_context())

@app.get("/signup", response_class=HTMLResponse)
async def signup(request: Request):
    return templates.TemplateResponse(request=request, name="signup.html", context=get_context())

@app.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse(request=request, name="forgot-password.html", context=get_context())

@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request):
    return templates.TemplateResponse(request=request, name="reset-password.html", context=get_context())

@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request):
    return templates.TemplateResponse(request=request, name="profile.html", context=get_context())

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="admin/dashboard.html", context=get_context())

@app.get("/admin/orders", response_class=HTMLResponse)
async def admin_orders(request: Request):
    return templates.TemplateResponse(request=request, name="admin/orders.html", context=get_context())

@app.get("/admin/messages", response_class=HTMLResponse)
async def admin_messages(request: Request):
    return templates.TemplateResponse(request=request, name="admin/messages.html", context=get_context())

@app.get("/admin/products", response_class=HTMLResponse)
async def admin_products_page(request: Request):
    """Admin products list. Auth handled client-side via admin/layout.html guard."""
    return templates.TemplateResponse(request=request, name="admin/products.html", context=get_context())

@app.get("/admin/products/new", response_class=HTMLResponse)
async def admin_products_new(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="admin/product_form.html",
        context={**get_context(), "mode": "create", "product_id": "", "product_json": "{}"},
    )

@app.get("/admin/products/{product_id}/edit", response_class=HTMLResponse)
async def admin_products_edit(request: Request, product_id: str):
    p = get_product(product_id, include_hidden=True)
    if not p:
        return HTMLResponse("Product not found", status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="admin/product_form.html",
        context={
            **get_context(),
            "mode": "edit",
            "product_id": product_id,
            "product_json": json.dumps(p),
            "price_optional": (p.get("slug") or product_id) in NO_PRICE_SLUGS,
        },
    )

@app.get("/admin/content", response_class=HTMLResponse)
async def admin_content_page(request: Request):
    """Admin Content overview — links to Main + Universe page editors."""
    return templates.TemplateResponse(request=request, name="admin/content.html", context=get_context())

@app.get("/admin/content/{page}", response_class=HTMLResponse)
async def admin_content_edit(request: Request, page: str):
    if page not in ("main", "universe"):
        return HTMLResponse("Unknown content page", status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="admin/content_edit.html",
        context={**get_context(), "page": page},
    )

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login(request: Request):
    return templates.TemplateResponse(request=request, name="admin/login.html", context=get_context())

# --- Customer Auth API Routes ---

@app.post("/api/auth/signup")
async def auth_signup(request: Request):
    """Customer signup with email/password"""
    body = await request.json()
    email = body.get("email", "").strip()
    password = body.get("password", "")
    full_name = body.get("full_name", "")

    try:
        # Create user via admin API (unconfirmed — must verify email)
        user = await _to_thread(supabase.auth.admin.create_user, {
            "email": email,
            "password": password,
            "email_confirm": False,
            "user_metadata": {"full_name": full_name}
        })

        if user.user:
            user_id = str(user.user.id)

            # Create profile (admin API guarantees user exists in auth.users)
            await _db(supabase.table("profiles").upsert({
                "id": user_id,
                "full_name": full_name,
                "email": email
            }))

            # Generate confirmation link without Supabase sending email
            scheme = request.headers.get("x-forwarded-proto", "http")
            host = request.headers.get("host", "localhost:3000")
            link_resp = await _to_thread(supabase.auth.admin.generate_link, {
                "type": "signup",
                "email": email,
                "password": password,
                "options": {"redirect_to": f"{scheme}://{host}/login"}
            })
            action_link = link_resp.properties.action_link

            # Send branded email via Resend (blocking HTTP to Resend — run in thread)
            await _to_thread(email_service.send_signup_confirmation, email, action_link, full_name)

            return JSONResponse({
                "success": True,
                "needs_confirmation": True,
                "message": "Check your email to confirm your account."
            })
        return JSONResponse({"error": "Signup failed"}, status_code=400)
    except Exception as e:
        error_msg = str(e)
        if "rate limit" in error_msg.lower():
            return JSONResponse({"error": error_msg}, status_code=429)
        if "already" in error_msg.lower() or "duplicate" in error_msg.lower() or "unique" in error_msg.lower():
            return JSONResponse({"error": "An account with this email already exists"}, status_code=409)
        return JSONResponse({"error": error_msg}, status_code=400)

@app.post("/api/auth/login")
async def auth_login(request: Request):
    """Customer login with email/password"""
    body = await request.json()
    email = body.get("email", "").strip()
    password = body.get("password", "")

    try:
        # Use anon client for auth (service role bypasses normal auth flows)
        result = await _to_thread(
            supabase_anon.auth.sign_in_with_password,
            {"email": email, "password": password},
        )
        if result.user:
            access_token = result.session.access_token if result.session else ""
            return JSONResponse({
                "success": True,
                "access_token": access_token,
                "user": {"id": str(result.user.id), "email": str(result.user.email or "")}
            })
        return JSONResponse({"error": "Invalid credentials"}, status_code=401)
    except Exception as e:
        error_msg = str(e)
        if "invalid" in error_msg.lower() or "credentials" in error_msg.lower():
            return JSONResponse({"error": "Invalid credentials"}, status_code=401)
        if "rate limit" in error_msg.lower():
            return JSONResponse({"error": error_msg}, status_code=429)
        return JSONResponse({"error": "Invalid credentials"}, status_code=401)

@app.post("/api/auth/forgot-password")
async def forgot_password(request: Request):
    """Send password reset email"""
    body = await request.json()
    email = body.get("email", "").strip()

    try:
        scheme = request.headers.get("x-forwarded-proto", "http")
        host = request.headers.get("host", "localhost:3000")
        link_resp = await _to_thread(supabase.auth.admin.generate_link, {
            "type": "recovery",
            "email": email,
            "options": {"redirect_to": f"{scheme}://{host}/reset-password"}
        })
        action_link = link_resp.properties.action_link

        await _to_thread(email_service.send_password_reset, email, action_link)
    except Exception:
        pass  # Always return success — never reveal if email exists

    return JSONResponse({"success": True, "message": "If an account exists, we've sent a reset link."})

@app.post("/api/auth/reset-password")
async def reset_password(request: Request):
    """Reset password using token from reset email"""
    body = await request.json()
    access_token = body.get("access_token", "")
    refresh_token = body.get("refresh_token", "")
    new_password = body.get("password", "")

    if not access_token or not new_password:
        return JSONResponse({"error": "Missing required fields"}, status_code=400)

    try:
        # Needs isolated client — set_session() mutates auth state
        def _do_reset():
            anon = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
            anon.auth.set_session(access_token, refresh_token)
            anon.auth.update_user({"password": new_password})

        await _to_thread(_do_reset)
        return JSONResponse({"success": True})
    except Exception as e:
        error_msg = str(e)
        if "expired" in error_msg.lower() or "invalid" in error_msg.lower():
            return JSONResponse({"error": "Reset link has expired. Please request a new one."}, status_code=401)
        return JSONResponse({"error": str(e)}, status_code=400)

# --- Admin Auth API Routes ---

@app.post("/api/admin/auth/send-link")
async def admin_send_link(request: Request, email: str = Form(...)):
    """Send magic link to allowed admin email only"""
    clean_email = email.lower().strip()
    if clean_email not in ALLOWED_EMAILS:
        return JSONResponse({"error": "This email is not authorized"}, status_code=403)

    try:
        scheme = request.headers.get("x-forwarded-proto", "http")
        host = request.headers.get("host", "localhost:3000")
        link_resp = await _to_thread(supabase.auth.admin.generate_link, {
            "type": "magiclink",
            "email": clean_email,
            "options": {"redirect_to": f"{scheme}://{host}/admin/auth/callback"}
        })
        action_link = link_resp.properties.action_link

        await _to_thread(email_service.send_admin_login_link, clean_email, action_link)

        return JSONResponse({"success": True, "message": "Check your email for a login link"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/admin/auth/callback", response_class=HTMLResponse)
async def admin_auth_callback(request: Request):
    """Handle magic link redirect — extracts token from URL hash client-side"""
    return templates.TemplateResponse(request=request, name="admin/auth-callback.html", context=get_context())

# --- Stripe Checkout API ---

async def _decrement_stock_for_items(items: list, source: str, order_id: Optional[str] = None) -> None:
    """Atomically reduce product stock for each line in a paid order.

    Called exactly once per order, on the pending→confirmed transition (and the
    fallback create path). Each line is settled by the single-statement
    `decrement_stock` SQL function so concurrent buyers can't both take the last
    unit. If a line raced to sold-out (function returns NULL) the customer has
    ALREADY PAID — we never reject; we clamp that product to 0 and log an oversell
    flag for the admin. Payment always wins.
    """
    if not isinstance(items, list):
        return
    touched = False
    for item in items:
        if not isinstance(item, dict):
            continue
        pid = item.get("id") or item.get("product_id")
        qty = int(item.get("quantity", 1) or 1)
        if not pid or qty <= 0:
            continue
        result = await _db(supabase.rpc("decrement_stock", {"p_id": pid, "p_qty": qty}))
        new_stock = result.data
        if isinstance(new_stock, list):
            new_stock = new_stock[0] if new_stock else None
        if new_stock is None:
            # Oversold during the open-checkout window — fulfill the paid order,
            # clamp to zero, and flag it for the admin to reconcile.
            await _db(supabase.table("products").update({"stock": 0}).eq("id", pid))
            print(f"[{source}] ⚠ OVERSELL: '{pid}' x{qty} exceeded stock; clamped to 0")
        await _stock_move(pid, -qty, "sale", 0 if new_stock is None else int(new_stock), order_id=order_id,
                          reason="" if new_stock is not None else "Sold more than was in stock: level set to 0, please check")
        touched = True
    if touched:
        await reload_products_cache()


async def _restock_for_items(items: list, source: str, order_id: Optional[str] = None, actor=None) -> None:
    """Return units to stock when a previously-paid order is cancelled."""
    if not isinstance(items, list):
        return
    touched = False
    for item in items:
        if not isinstance(item, dict):
            continue
        pid = item.get("id") or item.get("product_id")
        qty = int(item.get("quantity", 1) or 1)
        if not pid or qty <= 0:
            continue
        res = await _db(supabase.rpc("restock", {"p_id": pid, "p_qty": qty}))
        after = res.data[0] if isinstance(res.data, list) and res.data else res.data
        await _stock_move(pid, qty, "cancel_return", after if isinstance(after, int) else None,
                          order_id=order_id, actor=actor, reason="Order cancelled")
        touched = True
    if touched:
        await reload_products_cache()
        print(f"[{source}] restocked {len(items)} line(s)")


async def _confirm_order(order: dict, source: str) -> dict:
    """Transition a pending order to confirmed.

    Inserts order_items for analytics and clears the server cart.
    Idempotent — only runs once per order (status guard prevents duplicates).
    """
    order_id = order.get("id")
    if not order_id:
        return order

    await _db(supabase.table("orders").update({"status": "confirmed"}).eq("id", order_id))
    order["status"] = "confirmed"

    # Insert order_items for analytics (first transition only).
    # Batched: one INSERT for the whole cart instead of N sequential round-trips.
    items = order.get("items") or []
    if isinstance(items, list):
        rows = [
            {
                "order_id": order_id,
                "product_id": item.get("id"),
                "product_name": item.get("name", ""),
                "product_family": item.get("family", ""),
                "price": item.get("price", 0),
                "quantity": item.get("quantity", 1),
            }
            for item in items if isinstance(item, dict)
        ]
        if rows:
            await _db(supabase.table("order_items").insert(rows))

    # Reduce stock now that payment succeeded (idempotent: this transition runs once).
    await _decrement_stock_for_items(items, source, order_id)

    # Clear server cart
    user_id = order.get("user_id")
    if user_id:
        await _db(supabase.table("cart_items").delete().eq("user_id", user_id))

    print(f"[{source}] Order {order_id} pending → confirmed")
    await _order_event(order_id, None, "payment", "pending", "confirmed",
                       {"summary": "Payment confirmed. The order is ready for the warehouse."})
    _in_background(_notify_warehouse_safely(order_id))
    return order


async def _create_order_from_stripe_session(stripe_session, source: str = "webhook"):
    """Process a paid Stripe Checkout Session into a confirmed order.

    Three cases handled, all idempotent:
    1. Existing PENDING order (pre-created on session creation by /api/checkout/create-session)
       → transition to CONFIRMED, insert order_items, clear cart
    2. Existing CONFIRMED+ order (already processed by a previous webhook/route call)
       → defensive cart clear, return as-is
    3. No existing order (legacy path / pre-create failed / manual Stripe session)
       → create from session metadata as CONFIRMED directly

    Used by both the Stripe webhook handler and the /checkout/success route fallback.
    """
    session_id = stripe_session.id if hasattr(stripe_session, 'id') else stripe_session["id"]

    # Look up existing order (pre-created or already-processed)
    existing = await _db(
        supabase.table("orders").select("*").eq("stripe_session_id", session_id)
    )

    if existing.data:
        order = dict(existing.data[0])
        current_status = order.get("status")

        if current_status == "pending":
            # Case 1: pre-created pending order — payment just succeeded, transition to confirmed
            return await _confirm_order(order, source)

        # Case 2: already confirmed (or shipped/delivered/cancelled) — idempotent, defensive cart clear
        user_id = order.get("user_id")
        if user_id:
            await _db(supabase.table("cart_items").delete().eq("user_id", user_id))
        return order

    # Case 3: no existing order — fallback path (pre-create failed or unrecognized session)
    # Convert metadata to plain dict (StripeObject doesn't support .get())
    raw_meta = (stripe_session.metadata if hasattr(stripe_session, 'metadata') else stripe_session.get("metadata")) or {}
    if hasattr(raw_meta, 'to_dict'):
        meta = raw_meta.to_dict()
    else:
        meta = dict(raw_meta) if raw_meta else {}

    # Recalculate from product catalog (defense in depth — never trust client prices).
    # include_hidden=True: this path reconstructs orders whose product was visible at
    # checkout time but may have been hidden since. The customer already paid; serve them.
    items = json.loads(meta.get("items_json", "[]"))
    validated_items = []
    calculated_subtotal = 0
    for item in items:
        product = get_product(item.get("id"), include_hidden=True)
        if product:
            qty = item.get("quantity", 1)
            validated_items.append({
                "id": item["id"],
                "name": product["name"],
                "price": product["price"],
                "quantity": qty,
                "family": product.get("family", ""),
            })
            calculated_subtotal += product["price"] * qty

    if not validated_items:
        return None

    shipping = 25
    order_id = "MH-" + str(int(datetime.now().timestamp()))

    order_data = {
        "id": order_id,
        "user_id": meta.get("user_id"),
        "customer_name": meta.get("customer_name", ""),
        "customer_email": meta.get("customer_email", ""),
        "customer_phone": meta.get("customer_phone", ""),
        "shipping_address": {
            "line1": meta.get("shipping_line1", ""),
            "line2": meta.get("shipping_line2", ""),
            "city": meta.get("shipping_city", ""),
            "state": meta.get("shipping_state", ""),
            "postal_code": meta.get("shipping_postal_code", ""),
            "country": meta.get("shipping_country", ""),
        },
        "items": validated_items,
        "subtotal": calculated_subtotal,
        "shipping": shipping,
        "total": calculated_subtotal + shipping,
        "status": "confirmed",
        "stripe_session_id": session_id,
    }

    await _db(supabase.table("orders").insert(order_data))

    # Insert order_items for analytics — batched as one INSERT.
    rows = [
        {
            "order_id": order_id,
            "product_id": item["id"],
            "product_name": item["name"],
            "product_family": item.get("family", ""),
            "price": item["price"],
            "quantity": item["quantity"],
        }
        for item in validated_items
    ]
    if rows:
        await _db(supabase.table("order_items").insert(rows))

    # Reduce stock for this freshly-confirmed order (same as _confirm_order does
    # for the normal pre-created path).
    await _decrement_stock_for_items(validated_items, source, order_id)

    # Clear server cart
    user_id = meta.get("user_id")
    if user_id:
        await _db(supabase.table("cart_items").delete().eq("user_id", user_id))

    print(f"[{source}] Order {order_id} created from session metadata (fallback path)")
    await _order_event(order_id, None, "payment", None, "confirmed",
                       {"summary": "Payment confirmed. The order is ready for the warehouse."})
    _in_background(_notify_warehouse_safely(order_id))
    return order_data


@app.post("/api/checkout/create-session")
async def create_checkout_session(request: Request):
    """Create Stripe Checkout Session for payment"""
    user = await get_authenticated_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    # Pre-launch gate: no payment is started while coming-soon is on. The frontend
    # shows the "arriving soon" modal; this guard also stops a direct API hit.
    if CHECKOUT_COMING_SOON:
        return JSONResponse({"coming_soon": True})

    if not stripe_client:
        return JSONResponse({"error": "Payments not configured"}, status_code=503)

    body = await request.json()

    # Validate items against product catalog — never trust client prices.
    # Hidden products are rejected so the admin can pull a SKU instantly without
    # leaving an open window for purchases.
    validated_items = []
    calculated_subtotal = 0
    line_items = []

    for item in body.get("items", []):
        product = get_product(item.get("id"))
        if not product:
            return JSONResponse({"error": f"Unknown product: {item.get('id')}"}, status_code=400)
        qty = max(1, int(item.get("quantity", 1)))
        # Stock gate — never reveal the count, just block the over-order.
        available = product.get("stock", 0)
        if available <= 0:
            return JSONResponse(
                {"error": f"{product['name']} is currently out of stock. Please remove it from your cart."},
                status_code=409,
            )
        if qty > available:
            return JSONResponse(
                {"error": f"{product['name']} is no longer available in the requested quantity. Please reduce the amount in your cart."},
                status_code=409,
            )
        validated_items.append({
            "id": item["id"],
            "name": product["name"],
            "price": product["price"],
            "quantity": qty,
            "family": product.get("family", ""),
        })
        calculated_subtotal += product["price"] * qty
        line_items.append({
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": product["name"],
                    "description": f"Maison Henius — {product.get('family', '')}",
                },
                "unit_amount": int(round(product["price"] * 100)),  # Stripe requires int cents
            },
            "quantity": qty,
        })

    if not validated_items:
        return JSONResponse({"error": "Cart must contain at least one item"}, status_code=400)

    # Validate customer data
    customer = body.get("customer", {})
    if not customer.get("full_name") or not customer.get("email"):
        return JSONResponse({"error": "Name and email are required"}, status_code=400)

    address = customer.get("address", {})

    # Auto-save first checkout address to user's profile if they have none.
    # This way the next time they checkout, the address autofills from their saved
    # default. Non-fatal: if this fails, checkout still proceeds.
    try:
        if address.get("line1") and address.get("city"):
            existing_addrs = await _db(
                supabase.table("addresses").select("id").eq("user_id", str(user.id)).limit(1)
            )
            if not existing_addrs.data:
                await _db(supabase.table("addresses").insert({
                    "user_id": str(user.id),
                    "full_name": customer["full_name"],
                    "phone": customer.get("phone", ""),
                    "line1": address.get("line1", ""),
                    "line2": address.get("line2", ""),
                    "city": address.get("city", ""),
                    "state": address.get("state", ""),
                    "postal_code": address.get("postal_code", ""),
                    "country": address.get("country", ""),
                    "is_default": True,
                }))
                print(f"[create-session] Auto-saved first address for user {user.id}")
    except Exception as e:
        print(f"[create-session] Auto-save address failed (non-fatal): {e}")

    # Build URLs
    scheme = request.headers.get("x-forwarded-proto", "http")
    host = request.headers.get("host", "localhost:3000")
    base_url = f"{scheme}://{host}"

    # Store shipping + order data in metadata (retrieved by webhook)
    metadata = {
        "user_id": str(user.id),
        "customer_name": customer["full_name"],
        "customer_email": customer["email"],
        "customer_phone": customer.get("phone", ""),
        "shipping_line1": address.get("line1", ""),
        "shipping_line2": address.get("line2", ""),
        "shipping_city": address.get("city", ""),
        "shipping_state": address.get("state", ""),
        "shipping_postal_code": address.get("postal_code", ""),
        "shipping_country": address.get("country", ""),
        "items_json": json.dumps([{"id": i["id"], "quantity": i["quantity"]} for i in validated_items]),
    }

    try:
        # Stripe's Python SDK is sync — run the checkout session creation in a
        # worker thread to avoid blocking the asyncio event loop on the network
        # round-trip to Stripe.
        session = await _to_thread(
            stripe_client.v1.checkout.sessions.create,
            params={
                "mode": "payment",
                "line_items": line_items,
                "shipping_options": [{
                    "shipping_rate_data": {
                        "type": "fixed_amount",
                        "fixed_amount": {"amount": 2500, "currency": "usd"},
                        "display_name": "Standard Shipping",
                    },
                }],
                "customer_email": customer["email"],
                "metadata": metadata,
                "payment_intent_data": {
                    "receipt_email": customer["email"],
                },
                "success_url": f"{base_url}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
                "cancel_url": f"{base_url}/checkout",
            },
        )

        # Pre-create the order in our DB with status="pending" so abandoned
        # checkouts show up in /admin/orders. The webhook (or /checkout/success
        # fallback) transitions it to "confirmed" via _confirm_order() when
        # payment succeeds. If payment never completes, the order stays pending
        # and the admin can reach out to the customer using the stored email/phone.
        # Non-fatal: if this insert fails the user can still pay, and the
        # fallback path in _create_order_from_stripe_session() will create the
        # order from session metadata after payment.
        shipping_amount = 25
        try:
            pending_order_id = "MH-" + str(int(datetime.now().timestamp()))
            await _db(supabase.table("orders").insert({
                "id": pending_order_id,
                "user_id": str(user.id),
                "customer_name": customer["full_name"],
                "customer_email": customer["email"],
                "customer_phone": customer.get("phone", ""),
                "shipping_address": {
                    "line1": address.get("line1", ""),
                    "line2": address.get("line2", ""),
                    "city": address.get("city", ""),
                    "state": address.get("state", ""),
                    "postal_code": address.get("postal_code", ""),
                    "country": address.get("country", ""),
                },
                "items": validated_items,
                "subtotal": calculated_subtotal,
                "shipping": shipping_amount,
                "total": calculated_subtotal + shipping_amount,
                "status": "pending",
                "stripe_session_id": session.id,
            }))
            print(f"[create-session] Pending order {pending_order_id} pre-created for session {session.id}")
        except Exception as e:
            print(f"[create-session] Pre-create pending order failed (non-fatal): {e}")

        return JSONResponse({"url": session.url})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events"""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = Webhook.construct_event(
            payload.decode("utf-8"), sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        return JSONResponse({"error": "Invalid payload"}, status_code=400)
    except SignatureVerificationError:
        return JSONResponse({"error": "Invalid signature"}, status_code=400)

    if event.type == "checkout.session.completed":
        try:
            session = event.data.object
            print(f"[Stripe Webhook] checkout.session.completed: {session.id if hasattr(session, 'id') else session.get('id')}")
            await _create_order_from_stripe_session(session, source="webhook")
        except Exception as e:
            print(f"[Stripe Webhook] ERROR: {e}")
            traceback.print_exc()
            # Still return 200 so Stripe doesn't retry endlessly
            return JSONResponse({"received": True, "error": str(e)})

    return JSONResponse({"received": True})


@app.get("/checkout/success", response_class=HTMLResponse)
async def checkout_success(request: Request, session_id: str = ""):
    """Order confirmation page after Stripe payment.

    Self-healing: verifies the session with Stripe and runs the order helper,
    which handles all three cases idempotently:
    - Existing PENDING order (pre-created on session creation) → transitions to confirmed
    - Existing CONFIRMED order (webhook already processed) → defensive cart clear
    - No order exists → creates from session metadata as fallback
    """
    order_data = None

    if session_id and stripe_client:
        try:
            # Always go through Stripe API to verify the payment was actually completed
            # before transitioning the order. Prevents accidental confirmation if a user
            # navigates to /checkout/success manually with a stale session_id.
            stripe_session = await _to_thread(
                stripe_client.v1.checkout.sessions.retrieve, session_id
            )
            payment_status = getattr(stripe_session, "payment_status", None)

            if payment_status == "paid":
                order_data = await _create_order_from_stripe_session(
                    stripe_session, source="success-route"
                )
            else:
                # Payment not completed (manual navigation or expired session) —
                # try to surface the pending order if one exists, but don't transition it
                existing = await _db(
                    supabase.table("orders").select("*").eq("stripe_session_id", session_id)
                )
                if existing.data:
                    order_data = dict(existing.data[0])
        except Exception as e:
            print(f"[/checkout/success] ERROR: {e}")
            traceback.print_exc()

    return templates.TemplateResponse(
        request=request,
        name="checkout-success.html",
        context={**get_context(), "order": order_data},
    )


# --- Messages API ---

@app.post("/api/messages")
async def create_message(name: str = Form(...), email: str = Form(...), message: str = Form(...)):
    """Save contact message to Supabase"""
    name = name.strip()
    email = email.strip()
    message = message.strip()

    if not name or len(name) > 200:
        return JSONResponse({"error": "Name is required (max 200 characters)"}, status_code=400)
    if not email or len(email) > 320 or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return JSONResponse({"error": "Valid email is required"}, status_code=400)
    if not message or len(message) > 5000:
        return JSONResponse({"error": "Message is required (max 5000 characters)"}, status_code=400)

    try:
        msg_id = "MSG-" + str(int(time.time())).upper()
        await _db(supabase.table("messages").insert({
            "id": msg_id, "name": name, "email": email, "message": message
        }))
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({"error": "Failed to send message"}, status_code=500)

# --- Profile API ---

@app.get("/api/profile")
async def get_profile(request: Request):
    """Get user profile + addresses + order history"""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    token = auth_header.split(" ")[1]
    try:
        user_resp = await _to_thread(supabase.auth.get_user, token)
        if not user_resp or not user_resp.user:
            return JSONResponse({"error": "Invalid token"}, status_code=401)
        user_id = str(user_resp.user.id)
        user_email = str(user_resp.user.email or "")

        # Parallelize the three independent reads — asyncio.gather runs them
        # concurrently across worker threads instead of sequentially.
        profile, addresses, orders = await asyncio.gather(
            _db(supabase.table("profiles").select("*").eq("id", user_id).single()),
            _db(supabase.table("addresses").select("*").eq("user_id", user_id)),
            _db(supabase.table("orders").select("*").eq("user_id", user_id).order("created_at", desc=True)),
        )

        profile_data = dict(profile.data) if profile.data and isinstance(profile.data, dict) else {}
        profile_data["email"] = user_email

        return JSONResponse({
            "profile": profile_data,
            "addresses": addresses.data,
            "orders": orders.data,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.patch("/api/profile")
async def update_profile(request: Request):
    """Update user profile (full_name, phone)"""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    token = auth_header.split(" ")[1]
    try:
        user_resp = await _to_thread(supabase.auth.get_user, token)
        if not user_resp or not user_resp.user:
            return JSONResponse({"error": "Invalid token"}, status_code=401)
        user_id = str(user_resp.user.id)
        body = await request.json()
        update_data = {}
        if "full_name" in body:
            update_data["full_name"] = body["full_name"]
        if "phone" in body:
            update_data["phone"] = body["phone"]
        if update_data:
            await _db(supabase.table("profiles").update(update_data).eq("id", user_id))
        return JSONResponse({"success": True})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# --- Address API Routes ---

@app.post("/api/profile/addresses")
async def create_address(request: Request):
    user = await get_authenticated_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    body = await request.json()
    address_data = {
        "user_id": str(user.id),
        "full_name": body.get("full_name", ""),
        "phone": body.get("phone", ""),
        "line1": body.get("line1", ""),
        "line2": body.get("line2", ""),
        "city": body.get("city", ""),
        "state": body.get("state", ""),
        "postal_code": body.get("postal_code", ""),
        "country": body.get("country", ""),
        "is_default": body.get("is_default", False)
    }

    # If setting as default, unset other defaults first
    if address_data["is_default"]:
        await _db(supabase.table("addresses").update({"is_default": False}).eq("user_id", str(user.id)))

    result = await _db(supabase.table("addresses").insert(address_data))
    return JSONResponse({"success": True, "address": result.data[0] if result.data else None})


@app.patch("/api/profile/addresses/{address_id}")
async def update_address(request: Request, address_id: str):
    user = await get_authenticated_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    body = await request.json()
    # Only allow updating own addresses
    existing = await _db(
        supabase.table("addresses").select("*").eq("id", address_id).eq("user_id", str(user.id))
    )
    if not existing.data:
        return JSONResponse({"error": "Address not found"}, status_code=404)

    update_data = {}
    for field in ["full_name", "phone", "line1", "line2", "city", "state", "postal_code", "country"]:
        if field in body:
            update_data[field] = body[field]

    if update_data:
        result = await _db(supabase.table("addresses").update(update_data).eq("id", address_id))
        return JSONResponse({"success": True, "address": result.data[0] if result.data else None})
    return JSONResponse({"success": True})


@app.delete("/api/profile/addresses/{address_id}")
async def delete_address(request: Request, address_id: str):
    user = await get_authenticated_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    # Only allow deleting own addresses
    existing = await _db(
        supabase.table("addresses").select("*").eq("id", address_id).eq("user_id", str(user.id))
    )
    if not existing.data:
        return JSONResponse({"error": "Address not found"}, status_code=404)

    await _db(supabase.table("addresses").delete().eq("id", address_id))
    return JSONResponse({"success": True})


@app.patch("/api/profile/addresses/{address_id}/default")
async def set_default_address(request: Request, address_id: str):
    user = await get_authenticated_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    existing = await _db(
        supabase.table("addresses").select("*").eq("id", address_id).eq("user_id", str(user.id))
    )
    if not existing.data:
        return JSONResponse({"error": "Address not found"}, status_code=404)

    # Unset all defaults, then set this one
    await _db(supabase.table("addresses").update({"is_default": False}).eq("user_id", str(user.id)))
    await _db(supabase.table("addresses").update({"is_default": True}).eq("id", address_id))
    return JSONResponse({"success": True})

# --- Cart API Routes ---

def _enrich_cart_items(rows: list) -> list:
    """Attach an `at_max` flag (cart qty has reached available stock) and an
    `in_stock` flag to each cart row, so the UI can disable the + control and show
    sold-out state. The raw stock COUNT is deliberately never included — only booleans
    cross to the client, honoring the "never show the number" rule.
    A product that's been hidden or deleted reads as out of stock (unpurchasable)."""
    out = []
    for row in (rows or []):
        item = dict(row)
        product = get_product(row.get("product_id"))  # excludes hidden → treated as 0
        stock = product.get("stock", 0) if product else 0
        qty = row.get("quantity", 0) or 0
        item["at_max"] = qty >= stock
        item["in_stock"] = stock > 0
        out.append(item)
    return out


@app.get("/api/cart")
async def get_cart(request: Request):
    user = await get_authenticated_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    result = await _db(supabase.table("cart_items").select("*").eq("user_id", str(user.id)))
    return JSONResponse({"items": _enrich_cart_items(result.data)})


@app.post("/api/cart")
async def add_to_cart(request: Request):
    user = await get_authenticated_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    body = await request.json()
    user_id = str(user.id)
    product_id = body.get("product_id", "")

    # Validate product exists and use authoritative price (rejects hidden products too)
    product = get_product(product_id)
    if not product:
        return JSONResponse({"error": f"Unknown product: {product_id}"}, status_code=400)

    # Stock gate + clamp — a customer can never hold more units than exist.
    stock = product.get("stock", 0)
    if stock <= 0:
        return JSONResponse({"error": f"{product['name']} is out of stock"}, status_code=409)

    # Check if item already in cart
    existing = await _db(
        supabase.table("cart_items").select("*").eq("user_id", user_id).eq("product_id", product_id)
    )

    if existing.data:
        # Update quantity, clamped to available stock.
        row = existing.data[0]
        new_qty = min(row["quantity"] + body.get("quantity", 1), stock)
        await _db(supabase.table("cart_items").update({"quantity": new_qty}).eq("id", row["id"]))
    else:
        req_qty = max(1, min(int(body.get("quantity", 1) or 1), stock))
        await _db(supabase.table("cart_items").insert({
            "user_id": user_id,
            "product_id": product_id,
            "product_name": product["name"],
            "product_family": product.get("family", ""),
            "product_price": product["price"],
            "product_image": body.get("product_image", ""),
            "quantity": req_qty
        }))

    result = await _db(supabase.table("cart_items").select("*").eq("user_id", user_id))
    return JSONResponse({"success": True, "items": _enrich_cart_items(result.data)})


@app.patch("/api/cart/{item_id}")
async def update_cart_item(request: Request, item_id: str):
    user = await get_authenticated_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    body = await request.json()
    quantity = body.get("quantity", 1)

    existing = await _db(
        supabase.table("cart_items").select("*").eq("id", item_id).eq("user_id", str(user.id))
    )
    if not existing.data:
        return JSONResponse({"error": "Item not found"}, status_code=404)

    if quantity <= 0:
        await _db(supabase.table("cart_items").delete().eq("id", item_id))
    else:
        # Clamp to available stock so the cart can never exceed what exists.
        product = get_product(existing.data[0].get("product_id"))
        stock = product.get("stock", 0) if product else 0
        quantity = min(int(quantity), stock) if stock > 0 else 0
        if quantity <= 0:
            await _db(supabase.table("cart_items").delete().eq("id", item_id))
        else:
            await _db(supabase.table("cart_items").update({"quantity": quantity}).eq("id", item_id))

    result = await _db(supabase.table("cart_items").select("*").eq("user_id", str(user.id)))
    return JSONResponse({"success": True, "items": _enrich_cart_items(result.data)})


@app.delete("/api/cart/{item_id}")
async def remove_cart_item(request: Request, item_id: str):
    user = await get_authenticated_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    existing = await _db(
        supabase.table("cart_items").select("*").eq("id", item_id).eq("user_id", str(user.id))
    )
    if not existing.data:
        return JSONResponse({"error": "Item not found"}, status_code=404)

    await _db(supabase.table("cart_items").delete().eq("id", item_id))
    result = await _db(supabase.table("cart_items").select("*").eq("user_id", str(user.id)))
    return JSONResponse({"success": True, "items": _enrich_cart_items(result.data)})


@app.post("/api/cart/sync")
async def sync_cart(request: Request):
    """Merge localStorage cart with server cart on login"""
    user = await get_authenticated_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    body = await request.json()
    local_items = body.get("items", [])
    user_id = str(user.id)

    # Get existing server cart
    server_result = await _db(supabase.table("cart_items").select("*").eq("user_id", user_id))
    server_items = {item["product_id"]: item for item in (server_result.data or [])}

    # Merge: server wins on conflicts, only insert local-only items.
    # Batch the inserts so guest→login sync is one round-trip instead of N.
    rows_to_insert = []
    for local_item in local_items:
        pid = local_item.get("id", "")  # localStorage uses "id" as product_id
        if pid in server_items:
            continue  # Server wins — keep server quantity
        # Validate product exists and use authoritative price (skip hidden too)
        product = get_product(pid)
        if not product:
            continue  # Skip unknown/hidden products silently during sync
        # Skip out-of-stock products; clamp quantity to available stock.
        stock = product.get("stock", 0)
        if stock <= 0:
            continue
        qty = max(1, min(int(local_item.get("quantity", 1) or 1), stock))
        rows_to_insert.append({
            "user_id": user_id,
            "product_id": pid,
            "product_name": product["name"],
            "product_family": product.get("family", ""),
            "product_price": product["price"],
            "product_image": local_item.get("image", ""),
            "quantity": qty,
        })

    if rows_to_insert:
        await _db(supabase.table("cart_items").insert(rows_to_insert))

    # Return merged cart
    merged = await _db(supabase.table("cart_items").select("*").eq("user_id", user_id))
    return JSONResponse({"success": True, "items": _enrich_cart_items(merged.data)})

# ═══════════════════════════════════════════════════════════════════════════
# TEAM ACCESS + WAREHOUSE FULFILMENT (migration 014)
#
# Roles: "owner" (ALLOWED_EMAILS, hard-coded safety net, magic-link login),
#        "admin" (reserved for later), "fulfilment" (warehouse company).
# Enforcement lives HERE, on the server: every /api/admin/* endpoint goes through
# get_admin_user(), which refuses fulfilment accounts (deny by default). The
# warehouse only reaches the /api/fulfilment/* + /api/staff/* endpoints below,
# which return a fixed list of fields and accept only fulfilment actions.
# Staff accounts must be status "active" AND signed in with the 2-step code
# (JWT aal2) on every request, so suspending/revoking takes effect immediately.
# ═══════════════════════════════════════════════════════════════════════════

FULFILMENT_FLOW = ["new", "received", "preparing", "packed", "dispatched", "delivered"]
FULFILMENT_LABELS = {
    "new": "New", "received": "Received", "preparing": "Preparing",
    "packed": "Ready for dispatch", "dispatched": "Dispatched", "delivered": "Delivered",
}
ISSUE_TYPES = [
    "Incorrect or incomplete address",
    "Stock unavailable",
    "Damaged product",
    "Delay in preparation or dispatch",
    "Other",
]
# Only PAID orders reach the warehouse (no abandoned checkouts, no cancelled orders).
FULFILMENT_ORDER_STATUSES = ("confirmed", "shipped", "delivered")
# Customer contact details + street address are hidden from the warehouse on
# orders delivered longer ago than this.
PERSONAL_DATA_DAYS = 60
STAFF_PASSWORD_MIN = 10
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_BAN_FOREVER = "876000h"  # ~100 years: banned users cannot sign in or refresh

_ORDER_FIELDS = (
    "id,created_at,status,fulfilment_status,customer_name,customer_email,customer_phone,"
    "shipping_address,items,subtotal,shipping,total,courier,shipping_method,tracking_number,"
    "shipment_ref,dispatch_date,expected_delivery,actual_shipping_cost,actual_additional_cost,"
    "issue_type,issue_note,issue_raised_by,issue_raised_at,dispatched_at,delivered_at,"
    "fulfilment_updated_at"
)
_SHIPMENT_TEXT_FIELDS = ("courier", "shipping_method", "tracking_number", "shipment_ref", "expected_delivery")
_SHIPMENT_MONEY_FIELDS = ("actual_shipping_cost", "actual_additional_cost")
_SHIPMENT_LABELS = {
    "courier": "Courier", "shipping_method": "Shipping method", "tracking_number": "Tracking number",
    "shipment_ref": "Shipment reference", "dispatch_date": "Dispatch date",
    "expected_delivery": "Expected delivery", "actual_shipping_cost": "Actual shipping cost",
    "actual_additional_cost": "Additional delivery costs",
}


class Staff:
    """The signed-in person behind a request, with their role."""
    __slots__ = ("user", "user_id", "email", "role", "name", "staff_id")

    def __init__(self, user, email: str, role: str, name: str = "", staff_id: Optional[str] = None):
        self.user = user
        self.user_id = str(user.id)
        self.email = email
        self.role = role
        self.name = name
        self.staff_id = staff_id

    @property
    def label(self) -> str:
        if self.role == "owner":
            return "Maison Henius (owner)"
        return self.name or self.email


def _bearer(request: Request) -> str:
    h = request.headers.get("authorization", "")
    return h.split(" ", 1)[1].strip() if h.startswith("Bearer ") else ""


def _jwt_claims(token: str) -> dict:
    """Read the claims of a JWT that Supabase has ALREADY validated (get_user)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode()))
    except Exception:
        return {}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


_STAFF_LAST_SEEN: dict = {}  # user_id -> epoch seconds of the last last_seen_at write


async def _resolve_staff(request: Request) -> Optional[Staff]:
    """Who is calling, and may they act? None = not signed in, or not allowed."""
    token = _bearer(request)
    if not token:
        return None
    try:
        resp = await _to_thread(supabase.auth.get_user, token)
        user = resp.user if resp else None
    except Exception:
        return None
    if not user:
        return None
    email = str(user.email or "").lower()
    if email in ALLOWED_EMAILS:
        return Staff(user, email, "owner")
    try:
        res = await _db(
            supabase.table("staff_accounts").select("id,full_name,role,status")
            .eq("user_id", str(user.id)).limit(1)
        )
    except Exception as e:
        print(f"[staff] lookup failed: {e}")
        return None
    row = res.data[0] if res.data else None
    if not row or row.get("status") != "active":
        return None
    if _jwt_claims(token).get("aal") != "aal2":  # 2-step code is mandatory for staff
        return None
    now = time.time()
    if now - _STAFF_LAST_SEEN.get(str(user.id), 0) > 300:
        _STAFF_LAST_SEEN[str(user.id)] = now
        try:
            await _db(supabase.table("staff_accounts").update(
                {"last_seen_at": datetime.now(timezone.utc).isoformat()}).eq("id", row["id"]))
        except Exception:
            pass
    return Staff(user, email, row.get("role", "fulfilment"), row.get("full_name", ""), row["id"])


async def get_fulfilment_staff(request: Request) -> Optional[Staff]:
    """Anyone allowed on the Fulfilment pages: owner, admin, fulfilment."""
    return await _resolve_staff(request)


async def get_owner(request: Request) -> Optional[Staff]:
    staff = await _resolve_staff(request)
    return staff if staff and staff.role == "owner" else None


async def _log_staff(who, action: str, detail: str = "", request: Optional[Request] = None) -> None:
    """Activity log. Never breaks the request it records."""
    try:
        await _db(supabase.table("staff_activity").insert({
            "staff_email": getattr(who, "email", who or "") or "",
            "role": getattr(who, "role", ""),
            "action": action,
            "detail": (detail or "")[:500],
            "ip": _client_ip(request) if request else "",
        }))
    except Exception as e:
        print(f"[staff activity] log failed ({action}): {e}")


async def _order_event(order_id: str, actor: Optional[Staff], action: str,
                       from_value=None, to_value=None, details: Optional[dict] = None) -> None:
    """Append to the permanent order history. Never breaks the request it records."""
    try:
        await _db(supabase.table("order_events").insert({
            "order_id": order_id,
            "actor_email": actor.email if actor else "",
            "actor_name": actor.label if actor else "System",
            "actor_role": actor.role if actor else "system",
            "action": action,
            "from_value": None if from_value is None else str(from_value),
            "to_value": None if to_value is None else str(to_value),
            "details": details or {},
        }))
    except Exception as e:
        print(f"[order history] write failed for {order_id} ({action}): {e}")


def _money(v) -> Optional[float]:
    try:
        return None if v is None or v == "" else round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _parse_ts(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _order_view(o: dict, staff: Staff) -> dict:
    """The ONLY shape in which an order leaves the server on the Fulfilment pages.

    Never includes user_id, stripe_session_id or anything not listed here.
    Owners/admins additionally get the delivery-cost comparison.
    """
    items = []
    for it in o.get("items") or []:
        if not isinstance(it, dict):
            continue
        p = get_product(it.get("id"), include_hidden=True) or {}
        qty = int(it.get("quantity") or 1)
        price = float(it.get("price") or 0)
        items.append({
            "name": it.get("name") or p.get("name", ""),
            "brand": "Maison Henius",
            "sku": p.get("sku") or str(it.get("id") or ""),
            "variant": p.get("bottle_size", ""),
            "family": it.get("family") or p.get("family", ""),
            "quantity": qty,
            "unit_price": price,
            "line_total": round(price * qty, 2),
        })
    addr = o.get("shipping_address") or {}
    delivered_at = _parse_ts(o.get("delivered_at"))
    hide = (
        staff.role == "fulfilment"
        and o.get("fulfilment_status") == "delivered"
        and delivered_at is not None
        and datetime.now(timezone.utc) - delivered_at > timedelta(days=PERSONAL_DATA_DAYS)
    )
    customer = None if hide else {
        "name": o.get("customer_name", ""),
        "email": o.get("customer_email", ""),
        "phone": o.get("customer_phone", ""),
        "address": {k: addr.get(k, "") for k in ("line1", "line2", "city", "state", "postal_code", "country")},
        "instructions": addr.get("instructions", ""),
    }
    shipping = float(o.get("shipping") or 0)
    charges = {
        "subtotal": float(o.get("subtotal") or 0),
        "shipping": shipping,
        "door_to_door": 0.0,   # step 3 (shipping rates) adds these as stored amounts
        "additional": 0.0,
        "tax": 0.0,
        "discount": 0.0,
        "total": float(o.get("total") or 0),
    }
    view = {
        "id": o.get("id"),
        "created_at": o.get("created_at"),
        "payment_status": "Paid" if o.get("status") in FULFILMENT_ORDER_STATUSES else
                          ("Not paid" if o.get("status") == "pending" else "Cancelled"),
        "order_status": o.get("status"),
        "fulfilment_status": o.get("fulfilment_status") or "new",
        "items": items,
        "destination": {"city": addr.get("city", ""), "country": addr.get("country", "")},
        "customer": customer,
        "personal_data_hidden": hide,
        "charges": charges,
        "shipment": {
            "courier": o.get("courier") or "",
            "shipping_method": o.get("shipping_method") or "",
            "tracking_number": o.get("tracking_number") or "",
            "shipment_ref": o.get("shipment_ref") or "",
            "dispatch_date": o.get("dispatch_date") or "",
            "expected_delivery": o.get("expected_delivery") or "",
            "actual_shipping_cost": _money(o.get("actual_shipping_cost")),
            "actual_additional_cost": _money(o.get("actual_additional_cost")),
        },
        "issue": {
            "type": o.get("issue_type"), "note": o.get("issue_note") or "",
            "raised_by": o.get("issue_raised_by") or "", "raised_at": o.get("issue_raised_at"),
        } if o.get("issue_type") else None,
        "dispatched_at": o.get("dispatched_at"),
        "delivered_at": o.get("delivered_at"),
    }
    if staff.role == "fulfilment":
        # Owner decision: the warehouse sees ONE amount per order, the product
        # value for customs/insurance. No prices, fees or totals leave the server.
        for i in view["items"]:
            i.pop("unit_price", None)
            i.pop("line_total", None)
        view["charges"] = {"declared_value": charges["subtotal"]}
    if staff.role in ("owner", "admin"):
        charged = round(charges["shipping"] + charges["door_to_door"] + charges["additional"], 2)
        a1, a2 = view["shipment"]["actual_shipping_cost"], view["shipment"]["actual_additional_cost"]
        actual = None if a1 is None and a2 is None else round((a1 or 0) + (a2 or 0), 2)
        view["costs"] = {
            "charged": charged,
            "actual": actual,
            "difference": None if actual is None else round(charged - actual, 2),
        }
    return view


def _event_view(e: dict) -> dict:
    return {
        "at": e.get("created_at"),
        "who": e.get("actor_name") or e.get("actor_email") or "System",
        "role": e.get("actor_role", ""),
        "action": e.get("action", ""),
        "summary": (e.get("details") or {}).get("summary", ""),
    }


async def _load_order(order_id: str) -> Optional[dict]:
    res = await _db(supabase.table("orders").select(_ORDER_FIELDS).eq("id", order_id).limit(1))
    return res.data[0] if res.data else None


async def _order_detail(order_id: str, staff: Staff) -> Optional[dict]:
    o = await _load_order(order_id)
    if not o:
        return None
    if staff.role == "fulfilment" and o.get("status") not in FULFILMENT_ORDER_STATUSES:
        return None
    ev = await _db(
        supabase.table("order_events").select("created_at,actor_name,actor_email,actor_role,action,details")
        .eq("order_id", order_id).order("created_at", desc=False).limit(300)
    )
    out = {"order": _order_view(o, staff), "history": [_event_view(e) for e in (ev.data or [])],
           "role": staff.role, "issue_types": ISSUE_TYPES}
    if staff.role in ("owner", "admin"):
        out["notifications"] = await _notification_history(order_id)
    return out


def _clean_shipment(body: dict, current: dict):
    """Validate shipment fields the warehouse may write. Returns (changes, error)."""
    changes = {}
    for k in _SHIPMENT_TEXT_FIELDS:
        if k in body:
            v = str(body.get(k) or "").strip()
            if len(v) > 120:
                return None, f"{_SHIPMENT_LABELS[k]} must be 120 characters or fewer."
            if v != (current.get(k) or ""):
                changes[k] = v or None
    if "dispatch_date" in body:
        v = str(body.get("dispatch_date") or "").strip()
        if v:
            try:
                d = datetime.strptime(v, "%Y-%m-%d").date()
            except ValueError:
                return None, "Dispatch date must be a valid date."
            if d > (datetime.now(timezone.utc) + timedelta(days=1)).date():
                return None, "Dispatch date cannot be in the future."
        if v != (str(current.get("dispatch_date") or "")):
            changes["dispatch_date"] = v or None
    for k in _SHIPMENT_MONEY_FIELDS:
        if k in body:
            raw = body.get(k)
            if raw in (None, ""):
                v = None
            else:
                v = _money(raw)
                if v is None or v < 0 or v > 100000:
                    return None, f"{_SHIPMENT_LABELS[k]} must be an amount between 0 and 100,000."
            if v != _money(current.get(k)):
                changes[k] = v
    return changes, None


def _fmt_change(k, v) -> str:
    if v is None or v == "":
        return "—"
    if k in _SHIPMENT_MONEY_FIELDS:
        return f"USD {float(v):.2f}"
    return str(v)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _order_status_for(fs: str) -> str:
    return "delivered" if fs == "delivered" else "shipped" if fs == "dispatched" else "confirmed"


async def _notify_customer_status(order_id: str, new_status: str, request: Request,
                                  courier: str = "", tracking: str = "") -> bool:
    """Shipped / delivered email to the customer (same branded email as the Orders page)."""
    try:
        res = await _db(supabase.table("orders").select("customer_email,customer_name").eq("id", order_id))
        if not res.data or not res.data[0].get("customer_email"):
            return False
        scheme = request.headers.get("x-forwarded-proto", "http")
        host = request.headers.get("host", "localhost:3000")
        await _to_thread(
            email_service.send_order_status_email,
            res.data[0]["customer_email"], order_id, res.data[0].get("customer_name", ""),
            new_status, f"{scheme}://{host}", courier, tracking,
        )
        return True
    except Exception as e:
        print(f"[fulfilment] customer {new_status} email failed for {order_id}: {e}")
        return False


# ── Pages (HTML shells; data comes from the APIs, which enforce the roles) ──

@app.get("/admin/fulfilment", response_class=HTMLResponse)
async def admin_fulfilment_page(request: Request):
    return templates.TemplateResponse(request=request, name="admin/fulfilment.html", context=get_context())


@app.get("/admin/fulfilment/orders/{order_id}", response_class=HTMLResponse)
async def admin_fulfilment_order_page(request: Request, order_id: str):
    return templates.TemplateResponse(
        request=request, name="admin/fulfilment_order.html",
        context={**get_context(), "order_id": order_id},
    )


@app.get("/admin/fulfilment/login", response_class=HTMLResponse)
async def fulfilment_login_page(request: Request):
    return templates.TemplateResponse(request=request, name="admin/fulfilment_login.html",
                                      context={"mode": "login"})


@app.get("/admin/fulfilment/welcome", response_class=HTMLResponse)
async def fulfilment_welcome_page(request: Request):
    return templates.TemplateResponse(request=request, name="admin/fulfilment_login.html",
                                      context={"mode": "welcome"})


@app.get("/admin/team", response_class=HTMLResponse)
async def admin_team_page(request: Request):
    return templates.TemplateResponse(request=request, name="admin/team.html", context=get_context())


@app.get("/admin/account", response_class=HTMLResponse)
async def admin_account_page(request: Request):
    return templates.TemplateResponse(request=request, name="admin/account.html", context=get_context())


# ── Staff sign-in (password + mandatory 2-step code, via a per-request anon client) ──

def _anon_client():
    # Isolated client per request: set_session()/sign-in mutate the client's auth state.
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def _verified_totp(user) -> list:
    return [f for f in (getattr(user, "factors", None) or [])
            if getattr(f, "factor_type", "") == "totp" and getattr(f, "status", "") == "verified"]


async def _staff_row_for(user_id: str) -> Optional[dict]:
    res = await _db(supabase.table("staff_accounts").select("*").eq("user_id", user_id).limit(1))
    return res.data[0] if res.data else None


async def _start_enrolment(client, user) -> dict:
    """Begin linking an authenticator app. Drops any half-finished earlier attempt."""
    for f in (getattr(user, "factors", None) or []):
        if getattr(f, "factor_type", "") == "totp" and getattr(f, "status", "") != "verified":
            try:
                await _to_thread(client.auth.mfa.unenroll, {"factor_id": f.id})
            except Exception:
                pass
    enrol = await _to_thread(client.auth.mfa.enroll, {
        "factor_type": "totp", "issuer": "Maison Henius",
        "friendly_name": f"Maison Henius {int(time.time())}",
    })
    return {"factor_id": enrol.id, "qr_code": enrol.totp.qr_code, "secret": enrol.totp.secret}


def _tokens(session) -> dict:
    return {"access_token": session.access_token, "refresh_token": session.refresh_token,
            "expires_at": getattr(session, "expires_at", None)}


@app.post("/api/staff/login")
async def staff_login(request: Request):
    body = await request.json()
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    generic = JSONResponse({"error": "Incorrect email or password."}, status_code=401)
    if not email or not password:
        return generic
    if email in ALLOWED_EMAILS:
        return JSONResponse({"error": "Owners sign in with the email link on the Admin sign-in page."}, status_code=400)
    client = _anon_client()
    try:
        res = await _to_thread(client.auth.sign_in_with_password, {"email": email, "password": password})
    except Exception as e:
        if "rate" in str(e).lower():
            return JSONResponse({"error": "Too many attempts. Please wait a few minutes."}, status_code=429)
        await _log_staff(email, "sign_in_failed", "wrong email or password", request)
        return generic
    if not res or not res.user or not res.session:
        return generic
    row = await _staff_row_for(str(res.user.id))
    if not row or row.get("role") != "fulfilment":
        await _log_staff(email, "sign_in_failed", "not a fulfilment account", request)
        return generic
    if row.get("status") in ("suspended", "revoked"):
        await _log_staff(email, "sign_in_failed", f"account {row['status']}", request)
        return JSONResponse({"error": "This account does not have access. Please contact Maison Henius."}, status_code=403)
    verified = _verified_totp(res.user)
    if verified:
        return JSONResponse({"step": "verify", "factor_id": verified[0].id, **_tokens(res.session)})
    try:
        enrol = await _start_enrolment(client, res.user)
    except Exception as e:
        print(f"[staff] enrol failed for {email}: {e}")
        return JSONResponse({"error": "Could not start the 2-step set-up. Please try again."}, status_code=500)
    session = client.auth.get_session() or res.session
    return JSONResponse({"step": "enroll", **enrol, **_tokens(session)})


@app.post("/api/staff/accept")
async def staff_accept(request: Request):
    """Invitation / new set-up link: choose a password, then link the authenticator app."""
    body = await request.json()
    access_token = str(body.get("access_token") or "")
    refresh_token = str(body.get("refresh_token") or "")
    password = str(body.get("password") or "")
    if len(password) < STAFF_PASSWORD_MIN:
        return JSONResponse({"error": f"Please choose a password of at least {STAFF_PASSWORD_MIN} characters."}, status_code=400)
    client = _anon_client()
    try:
        res = await _to_thread(client.auth.set_session, access_token, refresh_token)
    except Exception:
        return JSONResponse({"error": "This link has expired or was already used. Please ask Maison Henius for a new one."}, status_code=401)
    user = res.user if res else None
    if not user:
        return JSONResponse({"error": "This link has expired or was already used. Please ask Maison Henius for a new one."}, status_code=401)
    row = await _staff_row_for(str(user.id))
    if not row or row.get("status") != "invited":
        return JSONResponse({"error": "This set-up link is no longer valid. Please contact Maison Henius."}, status_code=403)
    try:
        await _to_thread(client.auth.update_user, {"password": password})
    except Exception as e:
        msg = str(e).lower()
        if "weak" in msg or "password" in msg:
            return JSONResponse({"error": "Please choose a stronger password (mix words, numbers and symbols)."}, status_code=400)
        return JSONResponse({"error": "Could not save the password. Please try again."}, status_code=500)
    try:
        fresh = await _to_thread(client.auth.get_user)
        enrol = await _start_enrolment(client, fresh.user if fresh else user)
    except Exception as e:
        print(f"[staff] enrol failed: {e}")
        return JSONResponse({"error": "Could not start the 2-step set-up. Please try again."}, status_code=500)
    await _log_staff(str(user.email or ""), "password_set", "", request)
    return JSONResponse({"step": "enroll", **enrol, **_tokens(client.auth.get_session())})


@app.post("/api/staff/mfa/verify")
async def staff_mfa_verify(request: Request):
    body = await request.json()
    code = re.sub(r"\D", "", str(body.get("code") or ""))
    if len(code) != 6:
        return JSONResponse({"error": "Enter the 6-digit code from your authenticator app."}, status_code=400)
    client = _anon_client()
    try:
        await _to_thread(client.auth.set_session, str(body.get("access_token") or ""), str(body.get("refresh_token") or ""))
        res = await _to_thread(client.auth.mfa.challenge_and_verify,
                               {"factor_id": str(body.get("factor_id") or ""), "code": code})
    except Exception as e:
        msg = str(e).lower()
        if "expired" in msg or "session" in msg or "jwt" in msg:
            return JSONResponse({"error": "Your sign-in timed out. Please start again."}, status_code=401)
        return JSONResponse({"error": "That code is not right. Check the time on your phone is correct and try again."}, status_code=400)
    user = res.user
    row = await _staff_row_for(str(user.id)) if user else None
    if not row or row.get("role") != "fulfilment" or row.get("status") not in ("active", "invited"):
        return JSONResponse({"error": "This account does not have access. Please contact Maison Henius."}, status_code=403)
    email = str(user.email or "")
    if row["status"] == "invited":
        await _db(supabase.table("staff_accounts").update(
            {"status": "active", "activated_at": _now_iso(), "updated_at": _now_iso()}).eq("id", row["id"]))
        await _log_staff(email, "account_activated", "password and 2-step code set", request)
        # "Your access is ready" email with the sign-in link (first set-up only).
        try:
            await _to_thread(email_service.send_staff_ready, email, row.get("full_name", ""),
                             f"{_base_url(request)}/admin/fulfilment/login")
        except Exception as e:
            print(f"[staff] access-ready email failed for {email}: {e}")
    await _log_staff(email, "sign_in", "", request)
    return JSONResponse({"success": True, "role": "fulfilment", "name": row.get("full_name", ""),
                         "access_token": res.access_token, "refresh_token": res.refresh_token,
                         "expires_at": int(time.time()) + int(res.expires_in or 3600)})


@app.post("/api/staff/refresh")
async def staff_refresh(request: Request):
    """Keep a working session alive (works for owners' sessions too). Banned users cannot refresh."""
    body = await request.json()
    rt = str(body.get("refresh_token") or "")
    if not rt:
        return JSONResponse({"error": "Signed out"}, status_code=401)
    try:
        res = await _to_thread(_anon_client().auth.refresh_session, rt)
    except Exception:
        return JSONResponse({"error": "Signed out"}, status_code=401)
    if not res or not res.session:
        return JSONResponse({"error": "Signed out"}, status_code=401)
    return JSONResponse(_tokens(res.session))


@app.get("/api/staff/me")
async def staff_me(request: Request):
    staff = await _resolve_staff(request)
    if not staff:
        return JSONResponse({"error": "Not signed in"}, status_code=401)
    return JSONResponse({"email": staff.email, "role": staff.role, "name": staff.name})


@app.post("/api/staff/password")
async def staff_change_password(request: Request):
    staff = await _resolve_staff(request)
    if not staff:
        return JSONResponse({"error": "Not signed in"}, status_code=401)
    if staff.role == "owner":
        return JSONResponse({"error": "Owners sign in with an email link and have no password here."}, status_code=400)
    body = await request.json()
    password = str(body.get("password") or "")
    if len(password) < STAFF_PASSWORD_MIN:
        return JSONResponse({"error": f"Please choose a password of at least {STAFF_PASSWORD_MIN} characters."}, status_code=400)
    client = _anon_client()
    try:
        await _to_thread(client.auth.set_session, _bearer(request), str(body.get("refresh_token") or ""))
        await _to_thread(client.auth.update_user, {"password": password})
    except Exception as e:
        print(f"[staff] password change failed for {staff.email}: {e}")
        return JSONResponse({"error": "Could not change the password. Please sign in again and retry."}, status_code=400)
    await _log_staff(staff, "password_changed", "", request)
    return JSONResponse({"success": True})


# ── Fulfilment API (owner, admin, fulfilment) ──

@app.get("/api/fulfilment/orders")
async def fulfilment_orders(request: Request):
    staff = await get_fulfilment_staff(request)
    if not staff:
        return JSONResponse({"error": "Not signed in"}, status_code=401)
    res = await _db(
        supabase.table("orders").select(_ORDER_FIELDS)
        .in_("status", list(FULFILMENT_ORDER_STATUSES))
        .order("created_at", desc=True).limit(500)
    )
    return JSONResponse({"orders": [_order_view(o, staff) for o in (res.data or [])], "role": staff.role})


@app.get("/api/fulfilment/orders/{order_id}")
async def fulfilment_order(order_id: str, request: Request):
    staff = await get_fulfilment_staff(request)
    if not staff:
        return JSONResponse({"error": "Not signed in"}, status_code=401)
    detail = await _order_detail(order_id, staff)
    if not detail:
        return JSONResponse({"error": "Order not found"}, status_code=404)
    if staff.role == "fulfilment":
        await _log_staff(staff, "view_order", order_id, request)
    return JSONResponse(detail)


@app.patch("/api/fulfilment/orders/{order_id}")
async def fulfilment_update(order_id: str, request: Request):
    """Fulfilment actions only. Prices, fees, items, customer details and cancel/refund
    are NOT writable here, whatever the request contains."""
    staff = await get_fulfilment_staff(request)
    if not staff:
        return JSONResponse({"error": "Not signed in"}, status_code=401)
    o = await _load_order(order_id)
    if not o or o.get("status") not in FULFILMENT_ORDER_STATUSES:
        return JSONResponse({"error": "Order not found"}, status_code=404)
    body = await request.json()
    action = body.get("action")
    cur_fs = o.get("fulfilment_status") or "new"

    async def apply_shipment(fields: dict):
        if staff.role == "fulfilment" and o.get("fulfilment_status") in ("dispatched", "delivered"):
            return ("Shipment details are locked once an order is dispatched. "
                    "Add a comment to ask Maison Henius for a correction.")
        changes, err = _clean_shipment(fields, o)
        if err:
            return err
        if changes:
            changes["fulfilment_updated_at"] = _now_iso()
            await _db(supabase.table("orders").update(changes).eq("id", order_id))
            diff = {k: [_fmt_change(k, o.get(k)), _fmt_change(k, v)] for k, v in changes.items() if k in _SHIPMENT_LABELS}
            summary = "Shipment details: " + "; ".join(
                f"{_SHIPMENT_LABELS[k]}: {b}" if a == "—" else f"{_SHIPMENT_LABELS[k]}: {a} → {b}"
                for k, (a, b) in diff.items())
            await _order_event(order_id, staff, "shipment", None, None, {"changes": diff, "summary": summary})
            o.update(changes)
        return None

    if action == "shipment":
        err = await apply_shipment(body.get("shipment") or {})
        if err:
            return JSONResponse({"error": err}, status_code=400)

    elif action == "status":
        to = body.get("to")
        if to not in FULFILMENT_FLOW or to == cur_fs:
            return JSONResponse({"error": "Choose a different status."}, status_code=400)
        if staff.role == "fulfilment" and FULFILMENT_FLOW.index(to) < FULFILMENT_FLOW.index(cur_fs):
            return JSONResponse({"error": "Only Maison Henius can move an order back a step."}, status_code=403)
        if isinstance(body.get("shipment"), dict):
            err = await apply_shipment(body["shipment"])
            if err:
                return JSONResponse({"error": err}, status_code=400)
        if FULFILMENT_FLOW.index(to) >= FULFILMENT_FLOW.index("dispatched"):
            missing = [_SHIPMENT_LABELS[k].lower() for k in ("courier", "tracking_number", "dispatch_date") if not o.get(k)]
            if missing:
                return JSONResponse({"error": "Before dispatch, please enter: " + ", ".join(missing) + "."}, status_code=400)
        new_status = _order_status_for(to)
        upd = {"fulfilment_status": to, "fulfilment_updated_at": _now_iso(), "status": new_status}
        if to in ("dispatched", "delivered") and not o.get("dispatched_at"):
            upd["dispatched_at"] = _now_iso()
        if to == "delivered":
            upd["delivered_at"] = _now_iso()
        # Optimistic lock: only applies if nobody changed the step meanwhile.
        res = await _db(supabase.table("orders").update(upd).eq("id", order_id).eq("fulfilment_status", cur_fs))
        if not res.data:
            return JSONResponse({"error": "Someone else just updated this order. Please refresh the page."}, status_code=409)
        await _order_event(order_id, staff, "status", cur_fs, to, {
            "summary": f"Status: {FULFILMENT_LABELS[cur_fs]} → {FULFILMENT_LABELS[to]}"})
        if new_status != o.get("status") and new_status in ("shipped", "delivered"):
            sent = await _notify_customer_status(order_id, new_status, request,
                                                 o.get("courier") or "", o.get("tracking_number") or "")
            await _order_event(order_id, None, "email", None, new_status, {
                "summary": f"Customer emailed: order {new_status}" + (" (with courier and tracking)" if new_status == "shipped" else "")
                if sent else f"Customer {new_status} email could not be sent"})

    elif action == "raise_issue":
        itype = body.get("type")
        note = str(body.get("note") or "").strip()
        if itype not in ISSUE_TYPES:
            return JSONResponse({"error": "Choose the type of issue."}, status_code=400)
        if not note or len(note) > 1000:
            return JSONResponse({"error": "Please describe the issue (up to 1,000 characters)."}, status_code=400)
        await _db(supabase.table("orders").update({
            "issue_type": itype, "issue_note": note, "issue_raised_by": staff.label,
            "issue_raised_at": _now_iso(), "fulfilment_updated_at": _now_iso()}).eq("id", order_id))
        await _order_event(order_id, staff, "issue", None, itype, {"note": note, "summary": f"Issue raised: {itype}. {note}"})
        if staff.role == "fulfilment":
            _in_background(_notify_owners_issue(order_id, itype, note, staff.label))

    elif action == "resolve_issue":
        if not o.get("issue_type"):
            return JSONResponse({"error": "This order has no open issue."}, status_code=400)
        note = str(body.get("note") or "").strip()[:1000]
        await _db(supabase.table("orders").update({
            "issue_type": None, "issue_note": None, "issue_raised_by": None, "issue_raised_at": None,
            "fulfilment_updated_at": _now_iso()}).eq("id", order_id))
        await _order_event(order_id, staff, "issue_resolved", o.get("issue_type"), None, {
            "note": note, "summary": f"Issue resolved: {o.get('issue_type')}" + (f". {note}" if note else "")})

    elif action == "comment":
        text = str(body.get("text") or "").strip()
        if not text or len(text) > 1000:
            return JSONResponse({"error": "Write a comment (up to 1,000 characters)."}, status_code=400)
        await _order_event(order_id, staff, "comment", None, None, {"summary": f"Comment: {text}"})

    else:
        return JSONResponse({"error": "Unknown action"}, status_code=400)

    return JSONResponse(await _order_detail(order_id, staff))


# ── Team access (owners only) ──

def _staff_view(r: dict) -> dict:
    return {k: r.get(k) for k in ("id", "email", "full_name", "company", "role", "status",
                                  "invited_by", "invited_at", "activated_at", "last_seen_at")}


def _base_url(request: Request) -> str:
    scheme = request.headers.get("x-forwarded-proto", "http")
    host = request.headers.get("host", "localhost:3000")
    return f"{scheme}://{host}"


async def _send_setup_link(request: Request, email: str, name: str, reset: bool) -> bool:
    """Generate a one-time set-up link (invite, or recovery if the user already exists) and email it."""
    redirect = f"{_base_url(request)}/admin/fulfilment/welcome"
    link = None
    for kind in (("recovery", "invite") if reset else ("invite", "recovery")):
        try:
            resp = await _to_thread(supabase.auth.admin.generate_link,
                                    {"type": kind, "email": email, "options": {"redirect_to": redirect}})
            link = resp.properties.action_link
            break
        except Exception as e:
            print(f"[team] {kind} link failed for {email}: {e}")
    if not link:
        return False
    try:
        await _to_thread(email_service.send_staff_invite, email, link, name, reset)
        return True
    except Exception as e:
        print(f"[team] invite email failed for {email}: {e}")
        return False


@app.get("/api/admin/team")
async def admin_team(request: Request):
    owner = await get_owner(request)
    if not owner:
        return JSONResponse({"error": "Owner access required"}, status_code=401)
    staff_rows, activity = await asyncio.gather(
        _db(supabase.table("staff_accounts").select("*").order("invited_at", desc=True)),
        _db(supabase.table("staff_activity").select("*").order("created_at", desc=True).limit(100)),
    )
    try:
        rec = await _db(supabase.table("notification_recipients").select("*").order("created_at"))
        recipients = [{k: r.get(k) for k in ("id", "email", "label", "active")} for r in (rec.data or [])]
    except Exception:
        recipients = []
    return JSONResponse({
        "owners": list(ALLOWED_EMAILS),
        "recipients": recipients,
        "staff": [_staff_view(r) for r in (staff_rows.data or [])],
        "activity": [{k: a.get(k) for k in ("created_at", "staff_email", "role", "action", "detail")}
                     for a in (activity.data or [])],
    })


@app.post("/api/admin/team/invite")
async def admin_team_invite(request: Request):
    owner = await get_owner(request)
    if not owner:
        return JSONResponse({"error": "Owner access required"}, status_code=401)
    body = await request.json()
    email = str(body.get("email") or "").strip().lower()
    name = str(body.get("full_name") or "").strip()[:120]
    company = str(body.get("company") or "").strip()[:120]
    if not _EMAIL_RE.match(email):
        return JSONResponse({"error": "Enter a valid work email address."}, status_code=400)
    if email in ALLOWED_EMAILS:
        return JSONResponse({"error": "This is an owner address."}, status_code=400)
    existing = await _db(supabase.table("staff_accounts").select("id,status").eq("email", email).limit(1))
    if existing.data:
        return JSONResponse({"error": "This person is already on the team list. Use the buttons on their row."}, status_code=409)
    try:
        resp = await _to_thread(supabase.auth.admin.generate_link, {
            "type": "invite", "email": email,
            "options": {"redirect_to": f"{_base_url(request)}/admin/fulfilment/welcome"}})
    except Exception as e:
        if "already" in str(e).lower() or "registered" in str(e).lower():
            return JSONResponse({"error": "This email already has an account on the website (for example as a customer). Please use a different work email."}, status_code=409)
        print(f"[team] invite link failed for {email}: {e}")
        return JSONResponse({"error": "Could not create the invitation. Please try again."}, status_code=500)
    await _db(supabase.table("staff_accounts").insert({
        "user_id": str(resp.user.id), "email": email, "full_name": name, "company": company,
        "role": "fulfilment", "status": "invited", "invited_by": owner.email,
    }))
    sent = True
    try:
        await _to_thread(email_service.send_staff_invite, email, resp.properties.action_link, name, False)
    except Exception as e:
        print(f"[team] invite email failed for {email}: {e}")
        sent = False
    await _log_staff(owner, "team_invite", email, request)
    return JSONResponse({"success": True, "email_sent": sent})


@app.post("/api/admin/team/{staff_id}/action")
async def admin_team_action(staff_id: str, request: Request):
    owner = await get_owner(request)
    if not owner:
        return JSONResponse({"error": "Owner access required"}, status_code=401)
    body = await request.json()
    action = body.get("action")
    res = await _db(supabase.table("staff_accounts").select("*").eq("id", staff_id).limit(1))
    if not res.data:
        return JSONResponse({"error": "Not found"}, status_code=404)
    row = res.data[0]
    status, uid = row.get("status"), row.get("user_id")

    async def ban(on: bool):
        if uid:
            await _to_thread(supabase.auth.admin.update_user_by_id, uid,
                             {"ban_duration": _BAN_FOREVER if on else "none"})

    async def has_factor() -> bool:
        if not uid:
            return False
        try:
            u = await _to_thread(supabase.auth.admin.get_user_by_id, uid)
            return bool(_verified_totp(u.user))
        except Exception:
            return False

    new_status, note, sent = status, "", None
    try:
        if action == "suspend" and status in ("active", "invited"):
            await ban(True); new_status = "suspended"
        elif action == "revoke" and status != "revoked":
            await ban(True); new_status = "revoked"
        elif action == "reactivate" and status in ("suspended", "revoked"):
            await ban(False); new_status = "active" if await has_factor() else "invited"
        elif action == "resend" and status == "invited":
            sent = await _send_setup_link(request, row["email"], row.get("full_name", ""), reset=False)
        elif action == "reset" and status in ("active", "invited"):
            # New set-up link: choose a new password + link a new authenticator app.
            if uid:
                fl = await _to_thread(supabase.auth.admin.mfa.list_factors, {"user_id": uid})
                for f in (getattr(fl, "factors", None) or []):
                    await _to_thread(supabase.auth.admin.mfa.delete_factor, {"user_id": uid, "id": f.id})
            new_status = "invited"
            sent = await _send_setup_link(request, row["email"], row.get("full_name", ""), reset=True)
        else:
            return JSONResponse({"error": "This action is not available for this person right now."}, status_code=400)
    except Exception as e:
        print(f"[team] {action} failed for {row['email']}: {e}")
        return JSONResponse({"error": "That did not work. Please try again."}, status_code=500)
    if new_status != status:
        await _db(supabase.table("staff_accounts").update(
            {"status": new_status, "updated_at": _now_iso()}).eq("id", staff_id))
    await _log_staff(owner, f"team_{action}", row["email"], request)
    return JSONResponse({"success": True, "status": new_status, "email_sent": sent})


# ── Stock levels + stock history (migration 014, stock_movements) ──
# Every change to products.stock is recorded with its reason. Sales and
# cancellations are recorded automatically; owners adjust with a reason; the
# warehouse can only REQUEST "received" / "damaged" changes, which touch the
# stock only after an owner approves them on the Stock page (owners are emailed).

STOCK_KIND_LABELS = {
    "opening": "Starting level", "sale": "Sale", "cancel_return": "Returned (order cancelled)",
    "adjustment": "Adjustment", "received": "Stock received", "damaged": "Damaged / written off",
}
STOCK_REQUEST_KINDS = ("received", "damaged")
LOW_STOCK = 5


async def _stock_move(product_id: str, quantity: int, kind: str, stock_after, *, actor: Optional[Staff] = None,
                      reason: str = "", order_id: Optional[str] = None, status: str = "applied") -> Optional[dict]:
    """Write one stock history row. Never breaks the sale/cancel it records."""
    p = get_product(product_id, include_hidden=True) or {}
    try:
        res = await _db(supabase.table("stock_movements").insert({
            "product_id": product_id, "product_name": p.get("name", product_id), "kind": kind,
            "quantity": int(quantity), "stock_after": stock_after, "status": status,
            "reason": (reason or "")[:500], "order_id": order_id,
            "actor_email": actor.email if actor else "", "actor_name": actor.label if actor else "System",
            "actor_role": actor.role if actor else "system",
        }))
        return res.data[0] if res.data else None
    except Exception as e:
        print(f"[stock history] write failed for {product_id} ({kind}): {e}")
        return None


async def _apply_stock_change(product_id: str, change: int) -> Optional[int]:
    """Atomic +/- on products.stock. Returns the new level, or None if a removal
    would take it below zero (nothing changes then)."""
    if change >= 0:
        res = await _db(supabase.rpc("restock", {"p_id": product_id, "p_qty": change}))
    else:
        res = await _db(supabase.rpc("decrement_stock", {"p_id": product_id, "p_qty": -change}))
    v = res.data[0] if isinstance(res.data, list) and res.data else res.data
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _movement_view(r: dict) -> dict:
    return {
        "id": r.get("id"), "at": r.get("created_at"), "product_id": r.get("product_id"),
        "product": r.get("product_name"), "kind": r.get("kind"), "kind_label": STOCK_KIND_LABELS.get(r.get("kind"), r.get("kind")),
        "quantity": r.get("quantity"), "stock_after": r.get("stock_after"), "status": r.get("status"),
        "reason": r.get("reason") or "", "order_id": r.get("order_id"),
        "by": r.get("actor_name") or r.get("actor_email") or "System",
        "decided_by": r.get("decided_by"), "decided_at": r.get("decided_at"), "decision_note": r.get("decision_note") or "",
    }


@app.get("/admin/stock", response_class=HTMLResponse)
async def admin_stock_page(request: Request):
    return templates.TemplateResponse(request=request, name="admin/stock.html", context=get_context())


@app.get("/api/stock")
async def stock_overview(request: Request):
    """Stock levels (read-only for the warehouse) + history + pending requests."""
    staff = await get_fulfilment_staff(request)
    if not staff:
        return JSONResponse({"error": "Not signed in"}, status_code=401)
    own = staff.role in ("owner", "admin")
    products = []
    for p in sorted(get_products_dict(include_hidden=True).values(), key=lambda x: x.get("display_order", 0)):
        row = {"id": p.get("slug"), "name": p.get("name"), "sku": p.get("sku") or p.get("slug"),
               "stock": int(p.get("stock") or 0)}
        if own:
            row["hidden"] = bool(p.get("is_hidden"))
        products.append(row)
    res = await _db(supabase.table("stock_movements").select("*").order("created_at", desc=True).limit(400))
    moves = [_movement_view(r) for r in (res.data or [])]
    return JSONResponse({
        "role": staff.role, "low": LOW_STOCK, "products": products,
        "pending": [m for m in moves if m["status"] == "pending"],
        "history": [m for m in moves if m["status"] != "pending"],
    })


@app.post("/api/stock/requests")
async def stock_request(request: Request):
    """Warehouse records stock received / damaged. Waits for an owner's approval."""
    staff = await get_fulfilment_staff(request)
    if not staff:
        return JSONResponse({"error": "Not signed in"}, status_code=401)
    if staff.role != "fulfilment":
        return JSONResponse({"error": "Owners change stock directly with Adjust."}, status_code=400)
    body = await request.json()
    pid, kind = str(body.get("product_id") or ""), body.get("kind")
    p = get_product(pid, include_hidden=True)
    if not p:
        return JSONResponse({"error": "Choose a product."}, status_code=400)
    if kind not in STOCK_REQUEST_KINDS:
        return JSONResponse({"error": "Choose received or damaged."}, status_code=400)
    try:
        qty = int(body.get("quantity"))
    except (TypeError, ValueError):
        qty = 0
    if qty < 1 or qty > 100000:
        return JSONResponse({"error": "Enter a quantity of at least 1."}, status_code=400)
    note = str(body.get("note") or "").strip()
    if not note or len(note) > 500:
        return JSONResponse({"error": "Add a short note (for example the delivery reference or what was damaged)."}, status_code=400)
    change = qty if kind == "received" else -qty
    row = await _stock_move(pid, change, kind, None, actor=staff, reason=note, status="pending")
    if not row:
        return JSONResponse({"error": "Could not save the request. Please try again."}, status_code=500)
    await _log_staff(staff, f"stock_{kind}_requested", f"{p['name']} {change:+d}", request)
    try:
        await _to_thread(email_service.send_stock_request_notice, list(ALLOWED_EMAILS), staff.label,
                         p["name"], STOCK_KIND_LABELS[kind], change, int(p.get("stock") or 0), note,
                         f"{_base_url(request)}/admin/stock")
    except Exception as e:
        print(f"[stock] owner notification failed: {e}")
    return JSONResponse({"success": True})


@app.post("/api/admin/stock/adjust")
async def stock_adjust(request: Request):
    """Owner sets stock up or down, with a required reason."""
    if not await get_admin_user(request):
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    owner = await _resolve_staff(request)
    body = await request.json()
    pid = str(body.get("product_id") or "")
    if not get_product(pid, include_hidden=True):
        return JSONResponse({"error": "Product not found."}, status_code=404)
    try:
        change = int(body.get("change"))
    except (TypeError, ValueError):
        change = 0
    reason = str(body.get("reason") or "").strip()
    if change == 0 or abs(change) > 100000:
        return JSONResponse({"error": "Enter a change such as 10 or -2."}, status_code=400)
    if not reason or len(reason) > 500:
        return JSONResponse({"error": "Please give a reason."}, status_code=400)
    after = await _apply_stock_change(pid, change)
    if after is None:
        return JSONResponse({"error": "There is not enough stock to remove that many."}, status_code=409)
    await _stock_move(pid, change, "adjustment", after, actor=owner, reason=reason)
    await reload_products_cache()
    return JSONResponse({"success": True, "stock": after})


@app.post("/api/admin/stock/requests/{move_id}/decision")
async def stock_decision(move_id: str, request: Request):
    """Owner approves (applies) or rejects a warehouse stock request."""
    if not await get_admin_user(request):
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    owner = await _resolve_staff(request)
    body = await request.json()
    decision = body.get("decision")
    note = str(body.get("note") or "").strip()[:500]
    if decision not in ("approve", "reject"):
        return JSONResponse({"error": "Unknown decision"}, status_code=400)
    res = await _db(supabase.table("stock_movements").select("*").eq("id", move_id).limit(1))
    row = res.data[0] if res.data else None
    if not row or row.get("status") != "pending":
        return JSONResponse({"error": "This request was already decided. Please refresh."}, status_code=409)
    upd = {"decided_by": owner.label if owner else "Owner", "decided_at": _now_iso(), "decision_note": note}
    if decision == "reject":
        done = await _db(supabase.table("stock_movements").update({**upd, "status": "rejected"})
                         .eq("id", move_id).eq("status", "pending"))
        if not done.data:
            return JSONResponse({"error": "This request was already decided. Please refresh."}, status_code=409)
    else:
        after = await _apply_stock_change(row["product_id"], int(row["quantity"]))
        if after is None:
            return JSONResponse({"error": "There is not enough stock left to remove that many. Reject it, or adjust the stock first."}, status_code=409)
        done = await _db(supabase.table("stock_movements").update({**upd, "status": "applied", "stock_after": after})
                         .eq("id", move_id).eq("status", "pending"))
        if not done.data:  # decided by someone else in the same moment: undo our change
            await _apply_stock_change(row["product_id"], -int(row["quantity"]))
            return JSONResponse({"error": "This request was already decided. Please refresh."}, status_code=409)
        await reload_products_cache()
    await _log_staff(owner, f"stock_request_{decision}d", f"{row.get('product_name')} {int(row['quantity']):+d}", request)
    return JSONResponse({"success": True})


# ── Step 2: automatic emails (migration 015) ──
# 1. New paid order → email every active recipient on Team access (once per order;
#    the webhook and the thank-you page may both confirm the same payment).
# 2. Warehouse flags an issue → email the owners.
# Every attempt is logged in notification_log; owners can resend from the order page.
# Email detail follows the owner's choice: order, products, SKU, quantities, city,
# country, declared value. Phone, email and street address stay in the portal.

_COUNTRY_NAMES = {
    "JO": "Jordan", "AE": "United Arab Emirates", "SA": "Saudi Arabia", "KW": "Kuwait", "BH": "Bahrain",
    "OM": "Oman", "QA": "Qatar", "LB": "Lebanon", "EG": "Egypt", "US": "United States",
    "GB": "United Kingdom", "FR": "France", "DE": "Germany",
}
_BACKGROUND_TASKS: set = set()  # keep references so background email tasks aren't garbage-collected


def _in_background(coro) -> None:
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


class _WarehouseViewer:
    """Builds the email from exactly what the warehouse may see (_order_view rules)."""
    role = "fulfilment"


async def _warehouse_recipients() -> list:
    try:
        res = await _db(supabase.table("notification_recipients").select("email").eq("active", True))
        return [r["email"] for r in (res.data or []) if r.get("email")]
    except Exception as e:
        print(f"[notify] recipients lookup failed: {e}")
        return []


async def _log_notification(order_id, kind: str, recipient: str, status: str, error: str = "",
                            provider_id: str = "", triggered_by: str = "system") -> None:
    try:
        await _db(supabase.table("notification_log").insert({
            "order_id": order_id, "kind": kind, "recipient": recipient[:300], "status": status,
            "error": (error or "")[:500], "provider_id": provider_id or "", "triggered_by": triggered_by,
        }))
    except Exception as e:
        print(f"[notify] log write failed ({kind}, {order_id}): {e}")


async def _send_with_retry(fn, *args):
    """Send once, retry once after 2 s. Returns (ok, provider_id, error)."""
    err = ""
    for attempt in (1, 2):
        try:
            r = await _to_thread(fn, *args)
            pid = r.get("id") if isinstance(r, dict) else getattr(r, "id", "")
            return True, str(pid or ""), ""
        except Exception as e:
            err = str(e)[:300]
            if attempt == 1:
                await asyncio.sleep(2)
    return False, "", err


def _warehouse_email_data(o: dict) -> dict:
    v = _order_view(o, _WarehouseViewer())
    cc = v["destination"]["country"]
    return {
        "order_id": v["id"],
        "paid_on": o.get("created_at") or "",
        "items": [{"name": i["name"], "sku": i["sku"], "variant": i["variant"], "quantity": i["quantity"]} for i in v["items"]],
        "customer_name": (v["customer"] or {}).get("name", ""),
        "city": v["destination"]["city"],
        "country": _COUNTRY_NAMES.get(cc, cc),
        "declared_value": v["charges"]["declared_value"],
        "has_instructions": bool((v["customer"] or {}).get("instructions")),
    }


async def notify_warehouse_new_order(order_id: str, manual_by: Optional[str] = None) -> dict:
    """Email the warehouse about a paid order.

    Automatic (manual_by=None): at most once per order, claimed atomically through
    orders.warehouse_notified_at. Manual (owner pressed Resend): always sends.
    """
    kind = "warehouse_new_order"
    trigger = manual_by or "system"
    recipients = await _warehouse_recipients()
    if not recipients:
        await _log_notification(order_id, kind, "", "skipped", "No recipients set on Team access", triggered_by=trigger)
        return {"sent": 0, "failed": 0, "skipped": "no_recipients"}
    o = await _load_order(order_id)
    if not o or o.get("status") not in FULFILMENT_ORDER_STATUSES:
        return {"sent": 0, "failed": 0, "skipped": "not_paid"}
    if not manual_by:
        claim = await _db(supabase.table("orders").update({"warehouse_notified_at": _now_iso()})
                          .eq("id", order_id).is_("warehouse_notified_at", "null"))
        if not claim.data:
            return {"sent": 0, "failed": 0, "skipped": "already_sent"}
    data = _warehouse_email_data(o)
    link = f"{SITE_URL}/admin/fulfilment/orders/{quote(order_id)}"
    sent = failed = 0
    for r in recipients:
        ok, pid, err = await _send_with_retry(email_service.send_warehouse_new_order, r, data, link)
        await _log_notification(order_id, kind, r, "sent" if ok else "failed", err, pid, trigger)
        sent, failed = sent + ok, failed + (not ok)
    summary = f"Warehouse email (new order) sent to {sent} of {len(recipients)} recipient(s)"
    if failed:
        summary += f", {failed} failed"
    if manual_by:
        summary += " · resent by the owner"
    await _order_event(order_id, None, "email", None, "warehouse", {"summary": summary})
    return {"sent": sent, "failed": failed}


async def _notify_warehouse_safely(order_id: str) -> None:
    try:
        await notify_warehouse_new_order(order_id)
    except Exception as e:
        print(f"[notify] warehouse email for {order_id} failed: {e}")


async def _notify_owners_issue(order_id: str, issue_type: str, note: str, by: str) -> None:
    to = list(ALLOWED_EMAILS)
    ok, pid, err = await _send_with_retry(
        email_service.send_owner_issue_alert, to, order_id, issue_type, note, by,
        f"{SITE_URL}/admin/fulfilment/orders/{quote(order_id)}")
    await _log_notification(order_id, "owner_issue", ", ".join(to), "sent" if ok else "failed", err, pid)


async def _notification_history(order_id: str) -> list:
    try:
        res = await _db(supabase.table("notification_log").select("*").eq("order_id", order_id)
                        .order("created_at", desc=True).limit(50))
        return [{k: r.get(k) for k in ("created_at", "kind", "recipient", "status", "error", "triggered_by")}
                for r in (res.data or [])]
    except Exception:
        return []


@app.post("/api/admin/orders/{order_id}/notify-warehouse")
async def admin_resend_warehouse_email(order_id: str, request: Request):
    if not await get_admin_user(request):
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    owner = await _resolve_staff(request)
    o = await _load_order(order_id)
    if not o or o.get("status") not in FULFILMENT_ORDER_STATUSES:
        return JSONResponse({"error": "Only paid orders can be sent to the warehouse."}, status_code=400)
    result = await notify_warehouse_new_order(order_id, manual_by=owner.email if owner else "owner")
    if result.get("skipped") == "no_recipients":
        return JSONResponse({"error": "Add at least one recipient on Team access first."}, status_code=400)
    return JSONResponse(result)


@app.post("/api/admin/team/recipients")
async def admin_add_recipient(request: Request):
    owner = await get_owner(request)
    if not owner:
        return JSONResponse({"error": "Owner access required"}, status_code=401)
    body = await request.json()
    email = str(body.get("email") or "").strip().lower()
    if not _EMAIL_RE.match(email) or len(email) > 200:
        return JSONResponse({"error": "Enter a valid email address."}, status_code=400)
    existing = await _db(supabase.table("notification_recipients").select("id").eq("email", email).limit(1))
    if existing.data:
        return JSONResponse({"error": "This address is already on the list."}, status_code=409)
    await _db(supabase.table("notification_recipients").insert({
        "email": email, "label": str(body.get("label") or "").strip()[:120], "active": True, "added_by": owner.email}))
    await _log_staff(owner, "recipient_added", email, request)
    return JSONResponse({"success": True})


@app.patch("/api/admin/team/recipients/{rid}")
async def admin_toggle_recipient(rid: str, request: Request):
    owner = await get_owner(request)
    if not owner:
        return JSONResponse({"error": "Owner access required"}, status_code=401)
    body = await request.json()
    res = await _db(supabase.table("notification_recipients").update({"active": bool(body.get("active"))}).eq("id", rid))
    if not res.data:
        return JSONResponse({"error": "Not found"}, status_code=404)
    await _log_staff(owner, "recipient_on" if body.get("active") else "recipient_off", res.data[0].get("email", ""), request)
    return JSONResponse({"success": True})


@app.delete("/api/admin/team/recipients/{rid}")
async def admin_remove_recipient(rid: str, request: Request):
    owner = await get_owner(request)
    if not owner:
        return JSONResponse({"error": "Owner access required"}, status_code=401)
    res = await _db(supabase.table("notification_recipients").delete().eq("id", rid))
    if not res.data:
        return JSONResponse({"error": "Not found"}, status_code=404)
    await _log_staff(owner, "recipient_removed", res.data[0].get("email", ""), request)
    return JSONResponse({"success": True})


# --- Admin API Routes ---

@app.get("/api/admin/orders")
async def get_admin_orders(request: Request):
    admin = await get_admin_user(request)
    if not admin:
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    # Hard cap: most-recent 500 orders. Protects the admin dashboard from becoming
    # multi-second + multi-MB as order count grows. Pagination can be added later.
    result = await _db(
        supabase.table("orders").select("*").order("created_at", desc=True).limit(500)
    )
    return JSONResponse({"orders": result.data})

@app.get("/api/admin/messages")
async def get_admin_messages(request: Request):
    admin = await get_admin_user(request)
    if not admin:
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    result = await _db(
        supabase.table("messages").select("*").order("created_at", desc=True).limit(500)
    )
    return JSONResponse({"messages": result.data})

@app.get("/api/admin/stats")
async def get_admin_stats(request: Request):
    admin = await get_admin_user(request)
    if not admin:
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    # Parallelize the two independent selects
    orders, messages = await asyncio.gather(
        _db(supabase.table("orders").select("total,status")),
        _db(supabase.table("messages").select("id")),
    )
    orders_list = orders.data if orders.data and isinstance(orders.data, list) else []
    messages_list = messages.data if messages.data and isinstance(messages.data, list) else []

    # Only count paid orders toward revenue + total. Pending = abandoned checkout
    # (not paid yet), cancelled = refunded/voided. Both are excluded.
    PAID_STATUSES = {"confirmed", "shipped", "delivered"}
    paid_orders = [o for o in orders_list if isinstance(o, dict) and o.get("status") in PAID_STATUSES]
    pending_orders = [o for o in orders_list if isinstance(o, dict) and o.get("status") == "pending"]
    revenue = sum(float(o.get("total", 0)) for o in paid_orders)

    return JSONResponse({
        "total_orders": len(paid_orders),
        "pending_orders": len(pending_orders),
        "revenue": revenue,
        "messages": len(messages_list),
    })

@app.patch("/api/admin/orders/{order_id}")
async def update_order_status(order_id: str, request: Request):
    admin = await get_admin_user(request)
    if not admin:
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    body = await request.json()
    new_status = body["status"]

    # Read the order's prior state BEFORE updating — needed to decide whether
    # cancelling should return stock (only orders that actually decremented stock).
    prior = await _db(
        supabase.table("orders").select("status, items").eq("id", order_id)
    )
    prior_status = prior.data[0].get("status") if prior.data else None
    prior_items = prior.data[0].get("items") if prior.data else None

    await _db(supabase.table("orders").update({"status": new_status}).eq("id", order_id))

    # Keep the warehouse view in step with a status changed from the Orders page,
    # and record it in the order history. Non-fatal (e.g. before migration 014).
    try:
        owner = await _resolve_staff(request)
        await _order_event(order_id, owner, "order_status", prior_status, new_status,
                           {"summary": f"Order status (Orders page): {prior_status} → {new_status}"})
        sync = {}
        if new_status == "shipped":
            sync = {"fulfilment_status": "dispatched"}
        elif new_status == "delivered":
            sync = {"fulfilment_status": "delivered", "delivered_at": _now_iso()}
        if sync:
            cur = await _db(supabase.table("orders").select("fulfilment_status,dispatched_at").eq("id", order_id))
            cur_fs = (cur.data[0].get("fulfilment_status") if cur.data else None) or "new"
            if FULFILMENT_FLOW.index(sync["fulfilment_status"]) > FULFILMENT_FLOW.index(cur_fs):
                if not (cur.data and cur.data[0].get("dispatched_at")):
                    sync["dispatched_at"] = _now_iso()
                sync["fulfilment_updated_at"] = _now_iso()
                await _db(supabase.table("orders").update(sync).eq("id", order_id))
    except Exception as e:
        print(f"[orders] fulfilment sync skipped for {order_id}: {e}")

    # Auto-restock on cancel: only when moving INTO cancelled FROM a paid state that
    # had decremented stock (confirmed/shipped/delivered). Skips pending (never
    # decremented) and skips re-cancelling an already-cancelled order (no double-restock).
    DECREMENTED_STATUSES = {"confirmed", "shipped", "delivered"}
    if new_status == "cancelled" and prior_status in DECREMENTED_STATUSES:
        await _restock_for_items(prior_items or [], "cancel", order_id, await _resolve_staff(request))

    # Send email notification for shipped/delivered/cancelled
    email_sent = False
    if new_status in ("shipped", "delivered", "cancelled"):
        try:
            order = await _db(
                supabase.table("orders")
                .select("customer_email, customer_name")
                .eq("id", order_id)
            )
            if order.data:
                customer_email = order.data[0].get("customer_email")
                customer_name = order.data[0].get("customer_name", "")
                if customer_email:
                    scheme = request.headers.get("x-forwarded-proto", "http")
                    host = request.headers.get("host", "localhost:3000")
                    base_url = f"{scheme}://{host}"
                    await _to_thread(
                        email_service.send_order_status_email,
                        customer_email,
                        order_id,
                        customer_name,
                        new_status,
                        base_url,
                    )
                    email_sent = True
        except Exception as e:
            print(f"[Order Status Email] Failed for {order_id}: {e}")

    return JSONResponse({"success": True, "email_sent": email_sent})

@app.patch("/api/admin/messages/{msg_id}/read")
async def mark_message_read(msg_id: str, request: Request):
    admin = await get_admin_user(request)
    if not admin:
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    await _db(supabase.table("messages").update({"read": True}).eq("id", msg_id))
    return JSONResponse({"success": True})


# ─── Admin Products CRUD ──────────────────────────────────────────────────
# All endpoints gated by get_admin_user(). Cache is invalidated after any
# mutation so the public site reflects changes within the same request cycle.

SLUG_RE = re.compile(r"^[a-z0-9\-]+$")

def _validate_product_payload(body: dict, *, require_all: bool):
    """Validate and normalize a product payload. Returns (data, error_message)."""
    out: dict = {}

    if require_all or "slug" in body:
        slug = (body.get("slug") or "").strip().lower()
        if not slug or not SLUG_RE.fullmatch(slug):
            return None, "Slug must be lowercase letters, numbers, and dashes only"
        out["slug"] = slug

    if require_all or "name" in body:
        name = (body.get("name") or "").strip()
        if not name:
            return None, "Name is required"
        out["name"] = name

    if require_all or "family" in body:
        out["family"] = (body.get("family") or "").strip()

    if require_all or "price" in body:
        try:
            price = float(body.get("price") or 0)
        except (ValueError, TypeError):
            return None, "Price must be a number"
        if price < 0:
            return None, "Price cannot be negative"
        out["price"] = price

    if require_all or "stock" in body:
        try:
            stock = int(body.get("stock") or 0)
        except (ValueError, TypeError):
            return None, "Stock must be a whole number"
        if stock < 0:
            return None, "Stock cannot be negative"
        out["stock"] = stock

    for field in ("mood", "character", "description", "video"):
        if field in body:
            out[field] = body.get(field) or ""

    for field in ("card_image", "bottle_image", "mood_image", "explore_image"):
        if field in body:
            out[field] = body.get(field) or ""

    # Per-product editable page copy (migration 012). Empty strings are allowed
    # on PATCH (the DB DEFAULT will not fire on UPDATE, so an empty value is
    # what the owner intentionally saved — template fallback covers it).
    if "sku" in body:
        sku = str(body.get("sku") or "").strip().upper()
        if len(sku) > 40:
            return None, "SKU must be 40 characters or fewer"
        out["sku"] = sku

    for field in (
        "essence_label",
        "essence_tagline",
        "wearer_label",
        "composition_label",
        "composition_subtitle",
        "bottle_label",
        "bottle_size",
        "bottle_description",
    ):
        if field in body:
            out[field] = body.get(field) or ""

    if "display_order" in body:
        try:
            out["display_order"] = int(body.get("display_order") or 0)
        except (ValueError, TypeError):
            return None, "display_order must be an integer"

    if "is_hidden" in body:
        out["is_hidden"] = bool(body.get("is_hidden"))

    if "wearer" in body:
        w = body.get("wearer") or []
        if not isinstance(w, list):
            return None, "wearer must be a list"
        out["wearer"] = w

    if "notes" in body:
        n = body.get("notes") or {}
        if not isinstance(n, dict):
            return None, "notes must be an object"
        out["notes"] = n

    return out, None


@app.get("/api/admin/products")
async def admin_get_products(request: Request):
    admin = await get_admin_user(request)
    if not admin:
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    result = await _db(
        supabase.table("products").select("*").order("display_order")
    )
    return JSONResponse({"products": result.data or []})


@app.post("/api/admin/products")
async def admin_create_product(request: Request):
    admin = await get_admin_user(request)
    if not admin:
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    body = await request.json()
    data, error = _validate_product_payload(body, require_all=True)
    if error or not data:
        return JSONResponse({"error": error or "Invalid payload"}, status_code=400)
    # PK and slug stay in lockstep.
    data["id"] = data["slug"]
    try:
        result = await _db(supabase.table("products").insert(data))
        await reload_products_cache()
        product = (result.data or [None])[0]
        await _stock_move(data["id"], int(data.get("stock") or 0), "opening", int(data.get("stock") or 0),
                          actor=await _resolve_staff(request), reason="New product")
        return JSONResponse({"success": True, "product": product})
    except Exception as e:
        msg = str(e)
        if "duplicate" in msg.lower() or "unique" in msg.lower():
            return JSONResponse({"error": "A product with that slug already exists"}, status_code=409)
        return JSONResponse({"error": msg}, status_code=400)


@app.get("/api/admin/products/{product_id}")
async def admin_get_one_product(request: Request, product_id: str):
    admin = await get_admin_user(request)
    if not admin:
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    result = await _db(supabase.table("products").select("*").eq("id", product_id))
    rows = result.data or []
    if not rows:
        return JSONResponse({"error": "Product not found"}, status_code=404)
    return JSONResponse({"product": rows[0]})


@app.patch("/api/admin/products/{product_id}")
async def admin_update_product(request: Request, product_id: str):
    admin = await get_admin_user(request)
    if not admin:
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    body = await request.json()
    data, error = _validate_product_payload(body, require_all=False)
    if error:
        return JSONResponse({"error": error}, status_code=400)
    # Slug is the PK — block renaming via PATCH (would orphan order_items).
    data.pop("slug", None)
    if not data:
        return JSONResponse({"error": "No fields to update"}, status_code=400)
    before = get_product(product_id, include_hidden=True) or {}
    result = await _db(
        supabase.table("products").update(data).eq("id", product_id)
    )
    await reload_products_cache()
    rows = result.data or []
    if not rows:
        return JSONResponse({"error": "Product not found"}, status_code=404)
    if "stock" in data and before and int(before.get("stock", 0)) != data["stock"]:
        await _stock_move(product_id, data["stock"] - int(before.get("stock", 0)), "adjustment", data["stock"],
                          actor=await _resolve_staff(request), reason="Set on the product page")
    return JSONResponse({"success": True, "product": rows[0]})


@app.delete("/api/admin/products/{product_id}")
async def admin_delete_product(request: Request, product_id: str):
    admin = await get_admin_user(request)
    if not admin:
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    # Block delete if product has orders — would orphan order_items. Use Hide instead.
    refs = await _db(
        supabase.table("order_items").select("id").eq("product_id", product_id).limit(1)
    )
    if refs.data:
        return JSONResponse(
            {"error": "This product has existing orders. Hide it instead of deleting."},
            status_code=409,
        )
    await _db(supabase.table("products").delete().eq("id", product_id))
    await reload_products_cache()
    return JSONResponse({"success": True})


@app.patch("/api/admin/products/{product_id}/visibility")
async def admin_toggle_visibility(request: Request, product_id: str):
    admin = await get_admin_user(request)
    if not admin:
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    body = await request.json()
    is_hidden = bool(body.get("is_hidden", False))
    await _db(
        supabase.table("products").update({"is_hidden": is_hidden}).eq("id", product_id)
    )
    await reload_products_cache()
    return JSONResponse({"success": True, "is_hidden": is_hidden})


# ─── Admin file upload (Supabase Storage) ─────────────────────────────────

@app.post("/api/admin/upload")
async def admin_upload(
    request: Request,
    file: UploadFile = File(...),
    bucket: str = Form("product-images"),
):
    admin = await get_admin_user(request)
    if not admin:
        return JSONResponse({"error": "Admin access required"}, status_code=401)

    if bucket not in ALLOWED_BUCKETS:
        return JSONResponse({"error": f"Invalid bucket: {bucket}"}, status_code=400)

    content_type = (file.content_type or "application/octet-stream").lower()
    if bucket == "product-images" and content_type not in ALLOWED_IMAGE_TYPES:
        return JSONResponse(
            {"error": "Only WebP / JPEG / PNG images are allowed for products"},
            status_code=400,
        )
    if bucket == "page-media" and content_type not in (ALLOWED_IMAGE_TYPES | ALLOWED_VIDEO_TYPES):
        return JSONResponse({"error": "Unsupported file type"}, status_code=400)

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_SIZE:
        return JSONResponse(
            {"error": f"File too large (max {MAX_UPLOAD_SIZE // (1024*1024)} MB)"},
            status_code=413,
        )

    # Compose a safe storage path. Original stem is kept for debuggability,
    # uuid suffix guarantees uniqueness so re-uploads never overwrite by accident.
    raw_stem = Path(file.filename or "upload").stem
    safe_stem = re.sub(r"[^a-zA-Z0-9\-_]", "-", raw_stem)[:60].strip("-") or "upload"
    extension = Path(file.filename or "").suffix.lower()
    if not extension:
        ext_map = {
            "image/webp": ".webp", "image/jpeg": ".jpg", "image/png": ".png",
            "video/mp4": ".mp4", "video/webm": ".webm",
        }
        extension = ext_map.get(content_type, "")

    storage_path = f"{safe_stem}-{uuid.uuid4().hex[:8]}{extension}"

    try:
        await _to_thread(
            supabase.storage.from_(bucket).upload,
            storage_path,
            contents,
            {
                "content-type": content_type,
                "cache-control": "public, max-age=31536000, immutable",
            },
        )
    except Exception as e:
        return JSONResponse({"error": f"Upload failed: {e}"}, status_code=500)

    public_url = supabase.storage.from_(bucket).get_public_url(storage_path)
    if isinstance(public_url, str):
        public_url = public_url.rstrip("?")  # supabase-py occasionally tacks on '?'
    return JSONResponse({"url": public_url, "path": storage_path, "bucket": bucket})


# ─── Admin Content (CMS for Main + Universe pages) ────────────────────────
#
# Content blocks for the Main + Universe pages live in the page_content table.
# Templates pull values via the `content(section, field, fallback)` Jinja helper
# which is injected into the home + story route contexts (see below).
# The admin UI uses PAGE_CONTENT_SCHEMA to know what fields exist and how to
# render them (text / longtext / image / video). To add a new editable block:
#   1. Append an entry below.
#   2. Reference it in the corresponding template with content('section', 'field', 'fallback').
# The admin will pick it up automatically on next page load.

ALLOWED_CONTENT_PAGES = {"main", "universe"}

PAGE_CONTENT_SCHEMA = {
    "main": [
        # Hero (looping brand film at the top of the landing)
        # Hero film: one version per screen shape (the page picks automatically
        # and switches on rotation). All silent MP4; sound is a separate file.
        {"section": "hero", "field": "video", "type": "video",
         "label": "Hero film — wide, computers & screens held sideways (MP4, 1920×1080)", "group": "Hero",
         "help": "Used on: computers and large screens, and tablets held sideways. Wide (16:9) silent MP4, ideally 1920×1080, under 50 MB.",
         "default": "https://rmliognhrimbcwbyjikf.supabase.co/storage/v1/object/public/page-media/hero/mh-brand-film-1080.mp4"},
        {"section": "hero", "field": "video_mobile", "type": "video",
         "label": "Hero film — wide, smaller file for small screens held sideways (MP4, 1280×720)", "group": "Hero",
         "help": "Used on: small screens held sideways (phones turned sideways, small laptops). Wide (16:9) silent MP4, ideally 1280×720.",
         "default": "https://rmliognhrimbcwbyjikf.supabase.co/storage/v1/object/public/page-media/hero/mh-brand-film-720.mp4"},
        {"section": "hero", "field": "video_tablet", "type": "video",
         "label": "Hero film — upright tablets (MP4, 3:4, e.g. 810×1080)", "group": "Hero",
         "help": "Used on: tablets held upright. Upright 3:4 silent MP4, ideally 810×1080 or larger.",
         "default": "https://rmliognhrimbcwbyjikf.supabase.co/storage/v1/object/public/page-media/hero/mh-brand-film-tablet.mp4"},
        {"section": "hero", "field": "video_phone", "type": "video",
         "label": "Hero film — upright phones (MP4, 9:16, e.g. 720×1280)", "group": "Hero",
         "help": "Used on: phones held upright. Upright 9:16 silent MP4, ideally 720×1280 or 1080×1920.",
         "default": "https://rmliognhrimbcwbyjikf.supabase.co/storage/v1/object/public/page-media/hero/mh-brand-film-phone.mp4"},
        {"section": "hero", "field": "poster", "type": "image",
         "label": "Hero still image — wide (shown instantly while the film loads)", "group": "Hero",
         "help": "Still picture shown on computers and sideways screens for the first moment, while the film loads (ideally its first frame).",
         "default": "https://rmliognhrimbcwbyjikf.supabase.co/storage/v1/object/public/page-media/hero/mh-brand-film-poster.webp"},
        {"section": "hero", "field": "poster_tablet", "type": "image",
         "label": "Hero still image — upright tablets", "group": "Hero",
         "help": "Still picture shown on upright tablets while the film loads.",
         "default": "https://rmliognhrimbcwbyjikf.supabase.co/storage/v1/object/public/page-media/hero/mh-brand-film-poster-tablet.webp"},
        {"section": "hero", "field": "poster_phone", "type": "image",
         "label": "Hero still image — upright phones", "group": "Hero",
         "help": "Still picture shown on upright phones while the film loads.",
         "default": "https://rmliognhrimbcwbyjikf.supabase.co/storage/v1/object/public/page-media/hero/mh-brand-film-poster-phone.webp"},
        {"section": "hero", "field": "tagline", "type": "text", "required": True,
         "label": "Hero tagline (italic line over video)", "group": "Hero",
         "default": "Fragrance is not worn. It is lived."},

        # The House (brand quote on landing)
        {"section": "about", "field": "label", "type": "text", "required": True,
         "label": "House section label", "group": "The House",
         "default": "The House"},
        {"section": "about", "field": "quote", "type": "longtext", "required": True,
         "label": "Brand quote", "group": "The House",
         "default": '"Memory over product. Emotion over visibility."'},
        {"section": "about", "field": "subtext", "type": "longtext", "required": True,
         "label": "Brand description (paragraph below quote)", "group": "The House",
         "default": "Maison Henius transforms scent into memory. Each creation is an emotional identity rooted in craftsmanship and storytelling - not simply worn, but lived. The house exists between contrasts: garden and desert, life and silence. This duality defines every creation."},
        {"section": "about", "field": "origin_label", "type": "text", "required": True,
         "label": "Origin sub-label", "group": "The House",
         "default": "Our Origin"},
        {"section": "about", "field": "origin_heading", "type": "longtext", "required": True,
         "label": "Origin headline (two lines — use a line break)", "group": "The House",
         "default": "Where fragrant gardens meet\nthe mineral vastness of the desert"},
        {"section": "about", "field": "origin_body", "type": "longtext", "required": True,
         "label": "Origin body (separate paragraphs with a blank line)", "group": "The House",
         "default": (
             "Inspired by the landscapes of Jordan - where roses bloom beside ancient stone and amber sands stretch to the horizon - each composition reveals a subtle balance of freshness, depth, and character.\n\n"
             "Shaped by nature, memory, and exceptional raw materials, our fragrances unfold gradually, leaving an impression as unique as the land that inspired them."
         )},
        {"section": "about", "field": "image", "type": "image",
         "label": "Origin image (Wadi Rum)", "group": "The House",
         "default": "https://rmliognhrimbcwbyjikf.supabase.co/storage/v1/object/public/page-media/defaults/main-about-wadi-rum.webp"},
        {"section": "about", "field": "closing_quote", "type": "longtext", "required": True,
         "label": "Closing quote (after the origin block)", "group": "The House",
         "default": '"You do not buy a fragrance. You enter a story."'},

        # The Collection (heading above the 5-card grid)
        {"section": "collection", "field": "label", "type": "text", "required": True,
         "label": "Collection — small label", "group": "The Collection",
         "default": "The Collection"},
        {"section": "collection", "field": "heading", "type": "text", "required": True,
         "label": "Collection — headline", "group": "The Collection",
         "default": "Beyond Borders"},
        {"section": "collection", "field": "more_link", "type": "text", "required": True,
         "label": "Collection — \"Find More\" button text", "group": "The Collection",
         "default": "Find More"},
        {"section": "collection", "field": "more_sub", "type": "text",
         "label": "Collection — subtext under the button", "group": "The Collection",
         "default": "Browse the full collection"},

        # Between Garden and Desert (story section at bottom)
        {"section": "story", "field": "label", "type": "text", "required": True,
         "label": "Story — small label", "group": "Between Garden and Desert",
         "default": "Our World"},
        {"section": "story", "field": "heading", "type": "text", "required": True,
         "label": "Story — headline", "group": "Between Garden and Desert",
         "default": "Between Garden and Desert"},
        {"section": "story", "field": "col1", "type": "longtext", "required": True,
         "label": "Story — first paragraph", "group": "Between Garden and Desert",
         "default": "Where roses bloom beside ancient stone and amber sands stretch to the horizon - this is where Maison Henius begins. Each creation draws from the duality of Jordan: the lush fragrant gardens and the mineral vastness of the desert."},
        {"section": "story", "field": "col2", "type": "longtext", "required": True,
         "label": "Story — second paragraph", "group": "Between Garden and Desert",
         "default": "From these contrasts - life and silence, freshness and depth - emerges a language of scent that speaks to memory and emotion. Each composition unfolds gradually, leaving an impression as enduring as the land itself."},
        {"section": "story", "field": "image", "type": "image",
         "label": "Story — image", "group": "Between Garden and Desert",
         "default": "https://rmliognhrimbcwbyjikf.supabase.co/storage/v1/object/public/page-media/defaults/main-story-atelier.webp"},

        # Contact
        {"section": "contact", "field": "heading", "type": "text", "required": True,
         "label": "Contact — headline", "group": "Contact",
         "default": "We would love to hear from you"},
        {"section": "contact", "field": "subtext", "type": "text", "required": True,
         "label": "Contact — subtext", "group": "Contact",
         "default": "For inquiries, partnerships, or simply to share a memory."},

        # Footer — Social Links (global footer, rendered on every page via the
        # footer_social Jinja global, NOT the per-route content() helper).
        # Each link has a URL + a visibility toggle; a link renders only when
        # visible AND its URL is non-empty.
        {"section": "footer", "field": "instagram_url", "type": "text",
         "label": "Instagram URL", "group": "Footer — Social Links",
         "default": "https://www.instagram.com/maisonhenius"},
        {"section": "footer", "field": "instagram_visible", "type": "toggle",
         "label": "Show Instagram", "group": "Footer — Social Links",
         "default": "true"},
        {"section": "footer", "field": "tiktok_url", "type": "text",
         "label": "TikTok URL", "group": "Footer — Social Links",
         "default": "https://www.tiktok.com/@maison.henius"},
        {"section": "footer", "field": "tiktok_visible", "type": "toggle",
         "label": "Show TikTok", "group": "Footer — Social Links",
         "default": "true"},
        {"section": "footer", "field": "linkedin_url", "type": "text",
         "label": "LinkedIn URL", "group": "Footer — Social Links",
         "default": ""},
        {"section": "footer", "field": "linkedin_visible", "type": "toggle",
         "label": "Show LinkedIn", "group": "Footer — Social Links",
         "default": "false"},
    ],
    "universe": [
        # Hero
        {"section": "hero", "field": "label", "type": "text", "required": True,
         "label": "Hero — small label", "group": "Hero",
         "default": "Maison Henius"},
        {"section": "hero", "field": "title", "type": "text", "required": True,
         "label": "Hero — main title", "group": "Hero",
         "default": "Our Story"},
        {"section": "hero", "field": "subtitle", "type": "text", "required": True,
         "label": "Hero — subtitle (under the title)", "group": "Hero",
         "default": "Where Memory Becomes Fragrance"},
        {"section": "hero", "field": "image", "type": "image",
         "label": "Hero — background image", "group": "Hero",
         "default": "https://rmliognhrimbcwbyjikf.supabase.co/storage/v1/object/public/page-media/defaults/universe-hero-wadi-rum.webp"},

        # The Beginning
        {"section": "origin", "field": "label", "type": "text", "required": True,
         "label": "Beginning — small label", "group": "The Beginning",
         "default": "The Beginning"},
        {"section": "origin", "field": "heading", "type": "text", "required": True,
         "label": "Beginning — headline", "group": "The Beginning",
         "default": "Born Between Garden and Desert"},
        {"section": "origin", "field": "body", "type": "longtext", "required": True,
         "label": "Beginning — body (separate paragraphs with a blank line)", "group": "The Beginning",
         "default": (
             "Maison Henius was born where fragrant gardens meet the mineral vastness of the desert. "
             "Inspired by the landscapes of Jordan - where ochre sands hold the warmth of centuries and wild herbs perfume the evening air - "
             "the house creates fragrances shaped by nature, memory, and exceptional raw materials.\n\n"
             "This duality defines every creation. The lush, the arid. The fleeting, the eternal. "
             "Each composition reveals a subtle balance of freshness, depth, and character - a fragrance that gradually unfolds and leaves a unique impression on the skin and in the memory.\n\n"
             "The Maison exists between contrasts: life and silence, heritage and modernity, the intimate and the infinite. "
             "It is in this space that true elegance is found."
         )},
        {"section": "origin", "field": "image", "type": "image",
         "label": "Beginning — image", "group": "The Beginning",
         "default": "https://rmliognhrimbcwbyjikf.supabase.co/storage/v1/object/public/page-media/defaults/universe-origin-triptych.webp"},

        # The Craft
        {"section": "craft", "field": "label", "type": "text", "required": True,
         "label": "Craft — small label", "group": "The Craft",
         "default": "The Craft"},
        {"section": "craft", "field": "heading", "type": "text", "required": True,
         "label": "Craft — headline", "group": "The Craft",
         "default": "Every Detail, an Intention"},
        {"section": "craft", "field": "body", "type": "longtext", "required": True,
         "label": "Craft — body (separate paragraphs with a blank line)", "group": "The Craft",
         "default": (
             "At Maison Henius, fragrance begins with raw material. Rare, Expressive. Uncompromised. Each composition is built around what matters most \"the essence of the material itself\", Nothing is added to distract. Nothing is softened to please.\n\n"
             "The fragrance unfolds slowly. It evolves with skin, warmth and time.\n\n"
             "The bottle is an object of quiet refinement. Thick amber glass, lacquered in a gradient that deepens from warm golden-amber at the base to a rich darkness at the shoulder - evoking the transition from desert sand to twilight sky.\n\n"
             "A brass label plate, embossed and syringed with the Maison crest, rests against the glass like a jeweller's plaque. Serif lettering in deep Orange speaks of heritage without raising its voice.\n\n"
             "The cap tells its own story. Custom-cast in golden Zamac, its form draws from the ancient Ionic column - a fluted shaft rising to spiral volutes, crowned with a Greek key pattern band. The name of the house is engraved around the neck, a quiet signature of provenance and care.\n\n"
             "This is not packaging. It is an expression of the same artistry held within."
         )},
        {"section": "craft", "field": "image", "type": "image",
         "label": "Craft — image", "group": "The Craft",
         "default": "https://rmliognhrimbcwbyjikf.supabase.co/storage/v1/object/public/page-media/defaults/universe-craft-collection.webp"},

        # Our Pillars
        {"section": "values", "field": "label", "type": "text", "required": True,
         "label": "Pillars — small label", "group": "Our Pillars",
         "default": "Our Pillars"},
        {"section": "values", "field": "heading", "type": "text", "required": True,
         "label": "Pillars — headline", "group": "Our Pillars",
         "default": "What We Hold True"},
        {"section": "values", "field": "pillar_1_name", "type": "text", "required": True,
         "label": "Pillar 1 — name", "group": "Our Pillars",
         "default": "Elegance"},
        {"section": "values", "field": "pillar_1_desc", "type": "longtext", "required": True,
         "label": "Pillar 1 — description", "group": "Our Pillars",
         "default": "Refined, sophisticated, never loud. Every element is considered, every gesture precise."},
        {"section": "values", "field": "pillar_2_name", "type": "text", "required": True,
         "label": "Pillar 2 — name", "group": "Our Pillars",
         "default": "Exclusivity"},
        {"section": "values", "field": "pillar_2_desc", "type": "longtext", "required": True,
         "label": "Pillar 2 — description", "group": "Our Pillars",
         "default": "Not secretive, but selective. Designed for the connoisseur who values substance over spectacle."},
        {"section": "values", "field": "pillar_3_name", "type": "text", "required": True,
         "label": "Pillar 3 — name", "group": "Our Pillars",
         "default": "Warmth"},
        {"section": "values", "field": "pillar_3_desc", "type": "longtext", "required": True,
         "label": "Pillar 3 — description", "group": "Our Pillars",
         "default": "Inspired by ochre sands, amber tones, and golden heritage. A house that invites, never intimidates."},
        {"section": "values", "field": "pillar_4_name", "type": "text", "required": True,
         "label": "Pillar 4 — name", "group": "Our Pillars",
         "default": "Timelessness"},
        {"section": "values", "field": "pillar_4_desc", "type": "longtext", "required": True,
         "label": "Pillar 4 — description", "group": "Our Pillars",
         "default": "Enduring creations that transcend seasons and trends. What is true today remains true tomorrow."},
        {"section": "values", "field": "pillar_5_name", "type": "text", "required": True,
         "label": "Pillar 5 — name", "group": "Our Pillars",
         "default": "Cultural Depth"},
        {"section": "values", "field": "pillar_5_desc", "type": "longtext", "required": True,
         "label": "Pillar 5 — description", "group": "Our Pillars",
         "default": "Subtle references to heritage, travel, and artistry. A dialogue between civilisations, never a cliché."},

        # Parallax quote (over the Perfumer's Table image)
        {"section": "parallax", "field": "quote", "type": "longtext", "required": True,
         "label": "Parallax quote (over the Perfumer's Table image — use a line break to split lines)", "group": "Parallax Quote",
         "default": '"You do not buy a fragrance.\nYou enter a story."'},

        # Bottom CTA
        {"section": "cta", "field": "label", "type": "text", "required": True,
         "label": "Bottom CTA — small label", "group": "Bottom CTA",
         "default": "Beyond Borders"},
        {"section": "cta", "field": "heading", "type": "text", "required": True,
         "label": "Bottom CTA — headline", "group": "Bottom CTA",
         "default": "Discover the Collection"},
        {"section": "cta", "field": "subtext", "type": "text", "required": True,
         "label": "Bottom CTA — subtext", "group": "Bottom CTA",
         "default": "Five fragrances. Five journeys. One house."},
        {"section": "cta", "field": "button", "type": "text", "required": True,
         "label": "Bottom CTA — button text", "group": "Bottom CTA",
         "default": "Explore Fragrances"},
    ],
}


def _make_content_helper(content_map: dict):
    """Build a `content(section, field, fallback)` callable bound to a map of blocks.

    Used as a Jinja global in the home + story routes so templates can do:
        <h1>{{ content('hero', 'title', 'Maison Henius') }}</h1>
    """
    def lookup(section: str, field: str, fallback: str = "") -> str:
        key = f"{section}.{field}"
        block = content_map.get(key)
        if block:
            v = block.get("value")
            if v:
                return v
        return fallback
    return lookup


async def load_page_content(page: str) -> dict:
    """Fetch all content blocks for a page as a flat {'section.field': block} dict."""
    if page not in ALLOWED_CONTENT_PAGES:
        return {}
    try:
        result = await _db(supabase.table("page_content").select("*").eq("page", page))
        return {f"{b['section']}.{b['field']}": b for b in (result.data or [])}
    except Exception as e:
        print(f"[content] failed to load {page}: {e}")
        return {}


# ── Footer social links (global — rendered on EVERY page) ──────────────────
# The footer lives in layout.html and renders on every page, but the content()
# helper is only injected into the / and /story routes. So footer social links
# are exposed instead via a Jinja GLOBAL (footer_social) backed by this cache,
# refreshed at startup and on every Content save. Order = render order.
_FOOTER_SOCIAL_NETWORKS = [("instagram", "Instagram"), ("tiktok", "TikTok"), ("linkedin", "LinkedIn")]


def _footer_schema_default(field: str) -> str:
    for entry in PAGE_CONTENT_SCHEMA.get("main", []):
        if entry.get("section") == "footer" and entry.get("field") == field:
            return entry.get("default", "")
    return ""


def _build_footer_social(content_map: dict) -> list:
    """Merge saved page_content blocks over the schema defaults into a render-ready list."""
    links = []
    for name, label in _FOOTER_SOCIAL_NETWORKS:
        url_block = content_map.get(f"footer.{name}_url")
        url = (url_block.get("value") if url_block else "") or _footer_schema_default(f"{name}_url")
        vis_block = content_map.get(f"footer.{name}_visible")
        vis = (vis_block.get("value") if vis_block else "") or _footer_schema_default(f"{name}_visible")
        links.append({"name": name, "label": label, "url": url, "visible": vis == "true"})
    return links


# Seed from schema defaults at import so the footer always has values even before
# the first DB read (or if it fails). reload_footer_social() overrides from the DB.
_FOOTER_SOCIAL: list = _build_footer_social({})


async def reload_footer_social() -> None:
    """Rebuild the footer social-links cache: saved page_content merged over schema defaults."""
    global _FOOTER_SOCIAL
    _FOOTER_SOCIAL = _build_footer_social(await load_page_content("main"))


def get_footer_social() -> list:
    """Jinja global: visible footer links that have a URL, in render order. No DB hit."""
    return [l for l in _FOOTER_SOCIAL if l["visible"] and l["url"]]


templates.env.globals["footer_social"] = get_footer_social

@app.get("/api/admin/content/{page}")
async def admin_get_content(request: Request, page: str):
    admin = await get_admin_user(request)
    if not admin:
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    if page not in ALLOWED_CONTENT_PAGES:
        return JSONResponse({"error": "Unknown page"}, status_code=404)
    result = await _db(
        supabase.table("page_content").select("*").eq("page", page).order("display_order")
    )
    # Merge schema + saved values so admin UI knows every editable field
    # (saved or not), what type each one is, and the live default it falls
    # back to on the public site. The admin form pre-fills with `value` if
    # set, otherwise `default` — so the admin always edits the actual current
    # copy rather than a blank input.
    saved = {f"{b['section']}.{b['field']}": b for b in (result.data or [])}
    blocks = []
    for entry in PAGE_CONTENT_SCHEMA.get(page, []):
        key = f"{entry['section']}.{entry['field']}"
        s = saved.get(key, {})
        blocks.append({
            "section": entry["section"],
            "field": entry["field"],
            "field_type": entry["type"],
            "label": entry["label"],
            "group": entry.get("group", ""),
            "value": s.get("value", ""),
            "default": entry.get("default", ""),
            "required": bool(entry.get("required", False)),
            "help": entry.get("help", ""),
            "is_customized": bool(s.get("value")),
        })
    return JSONResponse({"page": page, "blocks": blocks})


@app.put("/api/admin/content/{page}")
async def admin_put_content(request: Request, page: str):
    """Bulk upsert all content blocks for a page in a single round-trip."""
    admin = await get_admin_user(request)
    if not admin:
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    if page not in ALLOWED_CONTENT_PAGES:
        return JSONResponse({"error": "Unknown page"}, status_code=404)
    body = await request.json()
    blocks = body.get("blocks") or []
    if not isinstance(blocks, list):
        return JSONResponse({"error": "blocks must be a list"}, status_code=400)
    rows = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        section = (b.get("section") or "").strip()
        field = (b.get("field") or "").strip()
        field_type = (b.get("field_type") or "text").strip()
        if not section or not field:
            continue
        # Intentionally omit display_order from the upsert payload — the
        # admin editor doesn't reorder fields (schema order is canonical),
        # so we never want to overwrite an existing row's display_order on
        # save. New rows fall back to the column default (0). PostgREST's
        # upsert only touches columns present in the payload.
        row = {
            "page": page,
            "section": section,
            "field": field,
            "field_type": field_type,
            "value": b.get("value") or "",
        }
        # Allow display_order ONLY when explicitly passed (e.g. a seed
        # script calling this endpoint), never from the standard admin save.
        if "display_order" in b and b.get("display_order") is not None:
            row["display_order"] = int(b.get("display_order") or 0)
        rows.append(row)
    if not rows:
        return JSONResponse({"success": True, "saved": 0})
    # Upsert by composite unique key (page, section, field) — defined in 001 migration.
    await _db(
        supabase.table("page_content").upsert(rows, on_conflict="page,section,field")
    )
    # Footer social links live under page=main; refresh the global cache so the
    # change shows on every page immediately (the footer isn't per-route).
    if page == "main":
        await reload_footer_social()
    return JSONResponse({"success": True, "saved": len(rows)})


# ─── Journal (blog) ───────────────────────────────────────────────────────
#
# Articles live in the blog_posts table (migration 013). Public pages:
#   /journal               list (featured story + grid + category filter)
#   /journal/{slug}        one article (SEO meta, JSON-LD, share buttons)
#   /journal/feed.xml      RSS feed (Google, Feedly, Pinterest, email tools)
# Admin: /admin/journal (list) + /admin/journal/new|{id}/edit, API under
# /api/admin/journal. Unlimited articles. A post is public only when status is
# "published" AND its publish date has arrived (a future date = scheduled).
# If the table can't be reached (e.g. migration 013 not yet run) the public
# Journal falls back to the six launch articles in journal_seed.py, so the
# page is never empty or broken.

import journal as journal_lib
from journal_seed import SEED_POSTS as JOURNAL_SEED_POSTS

JOURNAL_CATEGORIES = ["Origins", "Philosophy", "The Collection", "Fragrance Notes", "Craft", "Guides", "News"]


def _journal_seed_rows() -> list:
    return [{**p, "id": f"seed-{p['slug']}", "status": "published"} for p in JOURNAL_SEED_POSTS]


async def _journal_rows() -> tuple[list, bool]:
    """All articles (any status), newest first. Returns (rows, db_ready)."""
    try:
        result = await _db(
            supabase.table("blog_posts").select("*").order("published_at", desc=True)
        )
        return result.data or [], True
    except Exception as e:
        print(f"[journal] blog_posts unavailable, using launch articles: {e}")
        return _journal_seed_rows(), False


async def journal_live_posts() -> list:
    """Live (published + due) articles, enriched, newest first."""
    rows, _ = await _journal_rows()
    posts = [journal_lib.enrich(r) for r in rows if journal_lib.is_live(r)]
    oldest = datetime(1970, 1, 1).astimezone()
    posts.sort(key=lambda p: p["published_dt"] or oldest, reverse=True)
    return posts


def _journal_related_products(post: dict) -> list:
    out = []
    for slug in post.get("related_list", []):
        p = get_product(slug)
        if p:
            out.append(p)
    return out


def _abs_url(url: str) -> str:
    if not url:
        return ""
    return url if url.startswith("http") else SITE_URL + url


templates.env.globals["abs_url"] = _abs_url


@app.get("/journal", response_class=HTMLResponse)
@app.get("/journal/", response_class=HTMLResponse, include_in_schema=False)
async def journal_index(request: Request):
    posts = await journal_live_posts()
    featured = next((p for p in posts if p.get("is_featured")), posts[0] if posts else None)
    others = [p for p in posts if p is not featured]
    categories = [c for c in JOURNAL_CATEGORIES if any(p.get("category") == c for p in posts)]
    categories += sorted({p.get("category") for p in posts if p.get("category") and p.get("category") not in categories})
    return templates.TemplateResponse(
        request=request,
        name="journal/index.html",
        context={**get_context(), "featured": featured, "posts": others, "categories": categories},
    )


@app.get("/journal/feed.xml", include_in_schema=False)
async def journal_feed():
    posts = await journal_live_posts()
    items = []
    for p in posts[:30]:
        link = f"{SITE_URL}/journal/{quote(p['slug'])}"
        pub = p["published_dt"].strftime("%a, %d %b %Y %H:%M:%S +0000") if p["published_dt"] else ""
        img = _abs_url(p.get("hero_image", ""))
        enclosure = f'<enclosure url="{escape(img)}" type="image/webp" length="0"/>' if img.endswith(".webp") else ""
        items.append(
            "<item>"
            f"<title>{escape(p['title'])}</title><link>{link}</link><guid>{link}</guid>"
            f"<pubDate>{pub}</pubDate><category>{escape(p.get('category', ''))}</category>"
            f"<description>{escape(p['meta_description_final'])}</description>{enclosure}"
            "</item>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
        "<title>Maison Henius Journal</title>"
        f"<link>{SITE_URL}/journal</link>"
        f'<atom:link href="{SITE_URL}/journal/feed.xml" rel="self" type="application/rss+xml"/>'
        "<description>Stories of place, memory and craft from Maison Henius, a niche perfume house rooted in Jordan.</description>"
        "<language>en</language>" + "".join(items) + "</channel></rss>"
    )
    return Response(content=xml, media_type="application/rss+xml")


@app.get("/journal/{slug}", response_class=HTMLResponse)
async def journal_post(request: Request, slug: str):
    posts = await journal_live_posts()
    post = next((p for p in posts if p["slug"] == slug), None)
    if not post:
        return RedirectResponse("/journal", status_code=302)
    same = [p for p in posts if p is not post and p.get("category") == post.get("category")]
    rest = [p for p in posts if p is not post and p not in same]
    return templates.TemplateResponse(
        request=request,
        name="journal/post.html",
        context={
            **get_context(),
            "post": post,
            "body_html": journal_lib.render_body(post.get("body", "")),
            "related_products": _journal_related_products(post),
            "more_posts": (same + rest)[:3],
        },
    )


# ── Admin pages ──

@app.get("/admin/journal", response_class=HTMLResponse)
async def admin_journal_page(request: Request):
    return templates.TemplateResponse(request=request, name="admin/journal.html", context=get_context())


@app.get("/admin/journal/new", response_class=HTMLResponse)
async def admin_journal_new(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="admin/journal_form.html",
        context={**get_context(), "mode": "create", "post_id": "", "categories": JOURNAL_CATEGORIES},
    )


@app.get("/admin/journal/{post_id}/edit", response_class=HTMLResponse)
async def admin_journal_edit(request: Request, post_id: str):
    return templates.TemplateResponse(
        request=request,
        name="admin/journal_form.html",
        context={**get_context(), "mode": "edit", "post_id": post_id, "categories": JOURNAL_CATEGORIES},
    )


# ── Admin API ──

_JOURNAL_NOT_READY = ("The Journal database is not set up yet. Run migration "
                      "013_blog_posts.sql once (see docs/JOURNAL.md), then try again.")


@app.get("/api/admin/journal")
async def admin_journal_list(request: Request):
    if not await get_admin_user(request):
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    rows, ready = await _journal_rows()
    now = datetime.now().astimezone()
    out = []
    for r in rows:
        e = journal_lib.enrich(r)
        state = r.get("status", "draft")
        if state == "published" and not journal_lib.is_live(r, now):
            state = "scheduled"
        out.append({**r, "state": state, "reading_minutes": e["reading_minutes"],
                    "published_human": e["published_human"]})
    return JSONResponse({"posts": out, "db_ready": ready, "categories": JOURNAL_CATEGORIES})


@app.get("/api/admin/journal/{post_id}")
async def admin_journal_get(request: Request, post_id: str):
    if not await get_admin_user(request):
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    try:
        result = await _db(supabase.table("blog_posts").select("*").eq("id", post_id).limit(1))
    except Exception:
        return JSONResponse({"error": _JOURNAL_NOT_READY}, status_code=503)
    if not result.data:
        return JSONResponse({"error": "Article not found"}, status_code=404)
    return JSONResponse({"post": result.data[0]})


def _journal_db_error(e: Exception) -> JSONResponse:
    msg = str(e)
    if "duplicate" in msg.lower() or "unique" in msg.lower():
        return JSONResponse({"error": "Another article already uses that web address"}, status_code=409)
    if "blog_posts" in msg and ("does not exist" in msg or "schema cache" in msg):
        return JSONResponse({"error": _JOURNAL_NOT_READY}, status_code=503)
    return JSONResponse({"error": msg}, status_code=400)


@app.post("/api/admin/journal")
async def admin_journal_create(request: Request):
    if not await get_admin_user(request):
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    data, error = journal_lib.validate_payload(await request.json(), creating=True)
    if error:
        return JSONResponse({"error": error}, status_code=400)
    try:
        result = await _db(supabase.table("blog_posts").insert(data))
    except Exception as e:
        return _journal_db_error(e)
    return JSONResponse({"success": True, "post": (result.data or [None])[0]})


@app.patch("/api/admin/journal/{post_id}")
async def admin_journal_update(request: Request, post_id: str):
    if not await get_admin_user(request):
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    data, error = journal_lib.validate_payload(await request.json(), creating=False)
    if error:
        return JSONResponse({"error": error}, status_code=400)
    if data.get("status") == "published" and "published_at" in data and not data["published_at"]:
        data["published_at"] = datetime.now().astimezone().isoformat()
    if not data:
        return JSONResponse({"success": True})
    data["updated_at"] = datetime.now().astimezone().isoformat()  # no DB trigger (see migration 013)
    try:
        result = await _db(supabase.table("blog_posts").update(data).eq("id", post_id))
    except Exception as e:
        return _journal_db_error(e)
    if not result.data:
        return JSONResponse({"error": "Article not found"}, status_code=404)
    return JSONResponse({"success": True, "post": result.data[0]})


@app.delete("/api/admin/journal/{post_id}")
async def admin_journal_delete(request: Request, post_id: str):
    if not await get_admin_user(request):
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    try:
        await _db(supabase.table("blog_posts").delete().eq("id", post_id))
    except Exception as e:
        return _journal_db_error(e)
    return JSONResponse({"success": True})


@app.post("/api/admin/journal/preview")
async def admin_journal_preview(request: Request):
    """Render article text exactly as the public page will (for the editor's Preview tab)."""
    if not await get_admin_user(request):
        return JSONResponse({"error": "Admin access required"}, status_code=401)
    body = (await request.json()).get("body") or ""
    return JSONResponse({
        "html": str(journal_lib.render_body(body)),
        "words": len(journal_lib.plain_text(body).split()),
        "reading_minutes": journal_lib.reading_minutes(body),
    })
