from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from typing import Optional
import asyncio
import os
import re
import json
import time
import uuid
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
ALLOWED_EMAILS = ["osamah96@gmail.com", "husein.aldarawish@gmail.com"]

# --- Admin upload constraints ---
# Two Supabase Storage buckets gated by the admin endpoints below:
#   product-images: hero / card / mood / bottle / ingredient images
#   page-media:     editable CMS images + short videos for Main + Universe pages
ALLOWED_BUCKETS = {"product-images", "page-media"}
ALLOWED_IMAGE_TYPES = {"image/webp", "image/jpeg", "image/png"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/webm"}
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB hard ceiling — matches bucket policy

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
    """Extract and validate admin user from auth header"""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ")[1]
    try:
        user_resp = await _to_thread(supabase.auth.get_user, token)
        if user_resp and user_resp.user and str(user_resp.user.email) in ALLOWED_EMAILS:
            return user_resp.user
    except Exception:
        pass
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

# Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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


def jinja_page_media(value: str) -> str:
    return _resolve_url(value, "/static/assets/")


templates.env.filters["product_image"] = jinja_product_image
templates.env.filters["ingredient_image"] = jinja_ingredient_image
templates.env.filters["page_media"] = jinja_page_media


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
        "video": row.get("video", ""),
        "is_hidden": bool(row.get("is_hidden", False)),
        "display_order": int(row.get("display_order") or 0),
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
    """Populate the products cache before serving traffic."""
    try:
        await reload_products_cache()
        print(f"[startup] Loaded {len(_PRODUCTS_CACHE)} products from DB")
    except Exception as e:
        # Never let a transient Supabase blip block server boot — log and continue
        # with an empty cache. Routes that depend on products will 404 until next reload.
        print(f"[startup] FAILED to load products: {e}")


# --- Shared template context ---

def get_context():
    return {
        "supabase_url": SUPABASE_URL,
        "supabase_anon_key": SUPABASE_ANON_KEY,
    }

# --- Page Routes ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    content_map = await load_page_content("main")
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            **get_context(),
            "products": get_products_dict(),
            "content": _make_content_helper(content_map),
        },
    )

@app.get("/products", response_class=HTMLResponse)
@app.get("/products/", response_class=HTMLResponse)
async def products_index():
    return RedirectResponse("/shop", status_code=302)


@app.get("/shop", response_class=HTMLResponse)
async def shop(request: Request):
    """E-commerce grid showing all visible products with filter + sort."""
    products = get_products_dict()
    # Distinct families preserving display_order; templates iterate this for filter chips.
    families = []
    seen = set()
    for p in products.values():
        fam = p.get("family", "").strip()
        if fam and fam not in seen:
            seen.add(fam)
            families.append(fam)
    return templates.TemplateResponse(
        request=request,
        name="shop.html",
        context={**get_context(), "products": products, "families": families},
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
    return templates.TemplateResponse(request=request, name="checkout.html", context=get_context())

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

    # Clear server cart
    user_id = order.get("user_id")
    if user_id:
        await _db(supabase.table("cart_items").delete().eq("user_id", user_id))

    print(f"[{source}] Order {order_id} pending → confirmed")
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

    # Clear server cart
    user_id = meta.get("user_id")
    if user_id:
        await _db(supabase.table("cart_items").delete().eq("user_id", user_id))

    print(f"[{source}] Order {order_id} created from session metadata (fallback path)")
    return order_data


@app.post("/api/checkout/create-session")
async def create_checkout_session(request: Request):
    """Create Stripe Checkout Session for payment"""
    user = await get_authenticated_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

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
                "unit_amount": product["price"] * 100,  # Stripe uses cents
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

@app.get("/api/cart")
async def get_cart(request: Request):
    user = await get_authenticated_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    result = await _db(supabase.table("cart_items").select("*").eq("user_id", str(user.id)))
    return JSONResponse({"items": result.data})


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

    # Check if item already in cart
    existing = await _db(
        supabase.table("cart_items").select("*").eq("user_id", user_id).eq("product_id", product_id)
    )

    if existing.data:
        # Update quantity
        row = existing.data[0]
        new_qty = row["quantity"] + body.get("quantity", 1)
        await _db(supabase.table("cart_items").update({"quantity": new_qty}).eq("id", row["id"]))
    else:
        await _db(supabase.table("cart_items").insert({
            "user_id": user_id,
            "product_id": product_id,
            "product_name": product["name"],
            "product_family": product.get("family", ""),
            "product_price": product["price"],
            "product_image": body.get("product_image", ""),
            "quantity": body.get("quantity", 1)
        }))

    result = await _db(supabase.table("cart_items").select("*").eq("user_id", user_id))
    return JSONResponse({"success": True, "items": result.data})


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
        await _db(supabase.table("cart_items").update({"quantity": quantity}).eq("id", item_id))

    result = await _db(supabase.table("cart_items").select("*").eq("user_id", str(user.id)))
    return JSONResponse({"success": True, "items": result.data})


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
    return JSONResponse({"success": True, "items": result.data})


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
        rows_to_insert.append({
            "user_id": user_id,
            "product_id": pid,
            "product_name": product["name"],
            "product_family": product.get("family", ""),
            "product_price": product["price"],
            "product_image": local_item.get("image", ""),
            "quantity": local_item.get("quantity", 1),
        })

    if rows_to_insert:
        await _db(supabase.table("cart_items").insert(rows_to_insert))

    # Return merged cart
    merged = await _db(supabase.table("cart_items").select("*").eq("user_id", user_id))
    return JSONResponse({"success": True, "items": merged.data})

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

    await _db(supabase.table("orders").update({"status": new_status}).eq("id", order_id))

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

    for field in ("mood", "character", "description", "video"):
        if field in body:
            out[field] = body.get(field) or ""

    for field in ("card_image", "bottle_image", "mood_image", "explore_image"):
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
    result = await _db(
        supabase.table("products").update(data).eq("id", product_id)
    )
    await reload_products_cache()
    rows = result.data or []
    if not rows:
        return JSONResponse({"error": "Product not found"}, status_code=404)
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
        # The House (brand quote on landing)
        {"section": "about", "field": "quote", "type": "longtext",
         "label": "Brand quote", "group": "The House",
         "default": '"Memory over product. Emotion over visibility."'},
        {"section": "about", "field": "subtext", "type": "longtext",
         "label": "Brand description (paragraph below quote)", "group": "The House",
         "default": "Maison Henius transforms scent into memory. Each creation is an emotional identity rooted in craftsmanship and storytelling - not simply worn, but lived. The house exists between contrasts: garden and desert, life and silence. This duality defines every creation."},

        # The Collection (heading above the 5-card grid)
        {"section": "collection", "field": "label", "type": "text",
         "label": "Collection — small label", "group": "The Collection",
         "default": "The Collection"},
        {"section": "collection", "field": "heading", "type": "text",
         "label": "Collection — headline", "group": "The Collection",
         "default": "Beyond Borders"},

        # Between Garden and Desert (story section at bottom)
        {"section": "story", "field": "label", "type": "text",
         "label": "Story — small label", "group": "Between Garden and Desert",
         "default": "Our World"},
        {"section": "story", "field": "heading", "type": "text",
         "label": "Story — headline", "group": "Between Garden and Desert",
         "default": "Between Garden and Desert"},
        {"section": "story", "field": "col1", "type": "longtext",
         "label": "Story — first paragraph", "group": "Between Garden and Desert",
         "default": "Where roses bloom beside ancient stone and amber sands stretch to the horizon - this is where Maison Henius begins. Each creation draws from the duality of Jordan: the lush fragrant gardens and the mineral vastness of the desert."},
        {"section": "story", "field": "col2", "type": "longtext",
         "label": "Story — second paragraph", "group": "Between Garden and Desert",
         "default": "From these contrasts - life and silence, freshness and depth - emerges a language of scent that speaks to memory and emotion. Each composition unfolds gradually, leaving an impression as enduring as the land itself."},
        {"section": "story", "field": "image", "type": "image",
         "label": "Story — image", "group": "Between Garden and Desert",
         "default": "/static/assets/pictures/Jordan Landscape/Story.webp"},

        # Contact
        {"section": "contact", "field": "heading", "type": "text",
         "label": "Contact — headline", "group": "Contact",
         "default": "We would love to hear from you"},
        {"section": "contact", "field": "subtext", "type": "text",
         "label": "Contact — subtext", "group": "Contact",
         "default": "For inquiries, partnerships, or simply to share a memory."},
    ],
    "universe": [
        # Hero
        {"section": "hero", "field": "label", "type": "text",
         "label": "Hero — small label", "group": "Hero",
         "default": "Maison Henius"},
        {"section": "hero", "field": "title", "type": "text",
         "label": "Hero — main title", "group": "Hero",
         "default": "Our Story"},
        {"section": "hero", "field": "image", "type": "image",
         "label": "Hero — background image", "group": "Hero",
         "default": "/static/assets/pictures/Jordan Landscape/Wadi Rum.webp"},

        # The Beginning
        {"section": "origin", "field": "label", "type": "text",
         "label": "Beginning — small label", "group": "The Beginning",
         "default": "The Beginning"},
        {"section": "origin", "field": "heading", "type": "text",
         "label": "Beginning — headline", "group": "The Beginning",
         "default": "Born Between Garden and Desert"},
        {"section": "origin", "field": "body", "type": "longtext",
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
         "default": "/static/assets/pictures/Jordan Landscape/Maison Henius - universe.webp"},

        # The Craft
        {"section": "craft", "field": "label", "type": "text",
         "label": "Craft — small label", "group": "The Craft",
         "default": "The Craft"},
        {"section": "craft", "field": "heading", "type": "text",
         "label": "Craft — headline", "group": "The Craft",
         "default": "Every Detail, an Intention"},
        {"section": "craft", "field": "image", "type": "image",
         "label": "Craft — image", "group": "The Craft",
         "default": "/static/assets/pictures/Collection & Fragrances/beyond-borders-collection.webp"},

        # Our Pillars
        {"section": "values", "field": "label", "type": "text",
         "label": "Pillars — small label", "group": "Our Pillars",
         "default": "Our Pillars"},
        {"section": "values", "field": "heading", "type": "text",
         "label": "Pillars — headline", "group": "Our Pillars",
         "default": "What We Hold True"},
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
        rows.append({
            "page": page,
            "section": section,
            "field": field,
            "field_type": field_type,
            "value": b.get("value") or "",
            "display_order": int(b.get("display_order") or 0),
        })
    if not rows:
        return JSONResponse({"success": True, "saved": 0})
    # Upsert by composite unique key (page, section, field) — defined in 001 migration.
    await _db(
        supabase.table("page_content").upsert(rows, on_conflict="page,section,field")
    )
    return JSONResponse({"success": True, "saved": len(rows)})
