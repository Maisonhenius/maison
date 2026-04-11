from fastapi import FastAPI, Form, Request
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

# Product data (hardcoded — authoritative source for prices + validation)
PRODUCTS = {
    "out-of-control": {
        "slug": "out-of-control",
        "name": "Out of Control",
        "family": "Fruity-Floral",
        "price": 284,
        "mood": "Bold, daring, provocative",
        "character": "A scent for those who turn every moment into a declaration of freedom. Fresh and seductive, inspired by a modern Prince Charming.",
        "description": "At Maison Henius, each fragrance is a signature of emotion and memory, crafted with noble ingredients and timeless artistry. Every scent is a journey - an intimate companion to your moments, a bridge to feeling, and an expression of elegance lived.",
        "wearer": [
            {"name": "Bold", "desc": "Unapologetically present in every room"},
            {"name": "Daring", "desc": "Lives for the unexpected, thrives in the night"},
            {"name": "Provocative", "desc": "Leaves an addictive, unforgettable trail"}
        ],
        "notes": {
            "top": {"label": "Opening - Top Notes", "names": "Lemon - Nutmeg - Cool Spices", "desc": "The opening is bright and energizing with lemon, nutmeg and cool spices - a spark that cuts through the air.", "images": ["lemon", "nutmeg", "star-anise"]},
            "heart": {"label": "Heart - Middle Notes", "names": "Fig - Coconut - Freesia", "desc": "The heart reveals a creamy and slightly fruity facet built around fig, coconut and freesia - an unexpected softness.", "images": ["fig", "coconut", "freesia"]},
            "base": {"label": "Dry Down - Base Notes", "names": "Patchouli - Fruity Musk - Sandalwood", "desc": "The base blends patchouli, sandalwood and fruity musk to create a sensual, elegant and addictive trail.", "images": ["patchouli", "sandalwood", "musk"]}
        },
        "card_image": "card-out-of-control.webp",
        "bottle_image": "bottle-out-of-control.webp",
        "video": "1.mp4"
    },
    "parisian": {
        "slug": "parisian",
        "name": "Parisian",
        "family": "Floral-Gourmand",
        "price": 284,
        "mood": "Sophisticated, romantic, timeless",
        "character": "A scent for those who embody elegance in every step, and savor life like a Parisian. This fragrance celebrates the French art of living, inspired by an elegant Parisian breakfast.",
        "description": "At Maison Henius, each fragrance is a signature of emotion and memory, crafted with noble ingredients and timeless artistry. Every scent is a journey - an intimate companion to your moments, a bridge to feeling, and an expression of elegance lived.",
        "wearer": [
            {"name": "Sophisticated", "desc": "Effortlessly refined in taste and manner"},
            {"name": "Romantic", "desc": "Finds beauty in every small moment"},
            {"name": "Timeless", "desc": "Classic elegance that never fades"}
        ],
        "notes": {
            "top": {"label": "Opening - Top Notes", "names": "Coffee with Cream - Grapefruit - Red Berries", "desc": "The opening combines the freshness of grapefruit and red berries with a gourmand coffee-with-cream facet.", "images": ["coffee", "grapefruit", "red-berries"]},
            "heart": {"label": "Heart - Middle Notes", "names": "Rose - Peony - Jasmine", "desc": "The heart reveals a refined floral bouquet composed of rose, peony and jasmine, bringing softness and romance.", "images": ["rose", "peony", "jasmine"]},
            "base": {"label": "Dry Down - Base Notes", "names": "Croissant - Almond - Musk", "desc": "The base unfolds into a comforting gourmand accord of croissant, almond and musk, creating a soft and creamy signature.", "images": ["croissant", "almond", "musk"]}
        },
        "card_image": "card-parisian.webp",
        "bottle_image": "bottle-parisian.webp",
        "video": "2.mp4"
    },
    "velvet-waterfall": {
        "slug": "velvet-waterfall",
        "name": "Velvet Waterfall",
        "family": "Floral-Woody",
        "price": 284,
        "mood": "Flowing, sensual, luminous",
        "character": "A scent for those who discover beauty in balance, and elegance in every motion. This fragrance is inspired by the camel, a symbol of calm, resilience and elegance within the vastness of the desert.",
        "description": "At Maison Henius, each fragrance is a signature of emotion and memory, crafted with noble ingredients and timeless artistry. Every scent is a journey - an intimate companion to your moments, a bridge to feeling, and an expression of elegance lived.",
        "wearer": [
            {"name": "Flowing", "desc": "Moves with effortless grace through life"},
            {"name": "Sensual", "desc": "Embraces warmth and natural beauty"},
            {"name": "Luminous", "desc": "Radiates quiet, confident light"}
        ],
        "notes": {
            "top": {"label": "Opening - Top Notes", "names": "Pepper - Saffron - Incense", "desc": "The opening reveals warm and spicy notes of pepper and saffron, enriched with animalic touches of civet and incense that evoke the mineral depth of desert landscapes.", "images": ["pepper", "saffron", "incense"]},
            "heart": {"label": "Heart - Middle Notes", "names": "Rose - Violet - Lily of the Valley", "desc": "The floral heart combines rose, violet and lily of the valley, bringing a luminous and refined dimension to the composition.", "images": ["rose", "violet", "lily-of-the-valley"]},
            "base": {"label": "Dry Down - Base Notes", "names": "Musk - Cedarwood - Vetiver", "desc": "The base settles on a woody and musky foundation composed of cedarwood, moss and vetiver, leaving a warm, elegant and enveloping trail.", "images": ["musk", "cedarwood", "vetiver"]}
        },
        "card_image": "card-velvet-waterfall.webp",
        "bottle_image": "bottle-velvet-waterfall.webp",
        "video": "3.mp4"
    },
    "oh-my-dear": {
        "slug": "oh-my-dear",
        "name": "Oh My Dear!",
        "family": "Woody-Amber",
        "price": 284,
        "mood": "Intimate, graceful, sentimental",
        "character": "A scent for those who treasure elegance in the everyday and carry their memories like jewels of the soul. This fragrance explores a soft and enveloping suede accord evoking the texture of skin.",
        "description": "At Maison Henius, each fragrance is a signature of emotion and memory, crafted with noble ingredients and timeless artistry. Every scent is a journey - an intimate companion to your moments, a bridge to feeling, and an expression of elegance lived.",
        "wearer": [
            {"name": "Intimate", "desc": "Creates deep connections through presence"},
            {"name": "Graceful", "desc": "Carries elegance in the everyday"},
            {"name": "Sentimental", "desc": "Treasures memories like jewels of the soul"}
        ],
        "notes": {
            "top": {"label": "Opening - Top Notes", "names": "Oud - Saffron - Aldehydes", "desc": "The opening blends the intensity of oud and saffron with luminous aldehydic notes that bring brightness to the composition.", "images": ["oud", "saffron", "amber"]},
            "heart": {"label": "Heart - Middle Notes", "names": "Rose - Leather - Cypriol", "desc": "The heart reveals a refined accord of rose and leather, structured by cypriol which reinforces the woody and elegant character of the fragrance.", "images": ["rose", "leather", "cypriol"]},
            "base": {"label": "Dry Down - Base Notes", "names": "Amber - Vetiver - Vanilla", "desc": "The base combines amber, vetiver, cedarwood and vanilla to create a deep, warm and sophisticated trail.", "images": ["amber", "vetiver", "vanilla"]}
        },
        "card_image": "card-oh-my-dear.webp",
        "bottle_image": "bottle-oh-my-dear.webp",
        "video": "1.mp4"
    },
    "oud-passion": {
        "slug": "oud-passion",
        "name": "Oud Passion",
        "family": "Woody-Amber (Oud)",
        "price": 284,
        "mood": "Powerful, sophisticated, magnetic",
        "character": "A scent for those who wear confidence like a second skin. This fragrance is built around a balance between luminous freshness and woody depth.",
        "description": "At Maison Henius, each fragrance is a signature of emotion and memory, crafted with noble ingredients and timeless artistry. Every scent is a journey - an intimate companion to your moments, a bridge to feeling, and an expression of elegance lived.",
        "wearer": [
            {"name": "Powerful", "desc": "Commands attention without saying a word"},
            {"name": "Sophisticated", "desc": "Knows the art of restraint and presence"},
            {"name": "Magnetic", "desc": "Draws people in with quiet intensity"}
        ],
        "notes": {
            "top": {"label": "Opening - Top Notes", "names": "Grapefruit - Bergamot - Passion Fruit", "desc": "The opening draws inspiration from the freshness of citrus and exotic fruits: grapefruit, bergamot and passion fruit bring an immediate and modern dynamism.", "images": ["grapefruit", "bergamot", "passion-fruit"]},
            "heart": {"label": "Heart - Middle Notes", "names": "Moldavian Rose - Patchouli - Vetiver", "desc": "The heart revolves around Moldavian rose absolute, combined with patchouli and vetiver, reinforcing the woody and earthy structure of the composition.", "images": ["rose", "patchouli", "vetiver"]},
            "base": {"label": "Dry Down - Base Notes", "names": "Sandalwood - Oud - Leather", "desc": "The base reveals a noble and long-lasting accord of sandalwood, oud, leather and Orcanox, leaving a warm, enveloping and elegant trail.", "images": ["sandalwood", "oud", "leather"]}
        },
        "card_image": "card-oud-passion.webp",
        "bottle_image": "bottle-oud-passion.webp",
        "video": "2.mp4"
    }
}

# --- Shared template context ---

def get_context():
    return {
        "supabase_url": SUPABASE_URL,
        "supabase_anon_key": SUPABASE_ANON_KEY,
    }

# --- Page Routes ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={**get_context(), "products": PRODUCTS})

@app.get("/products", response_class=HTMLResponse)
@app.get("/products/", response_class=HTMLResponse)
async def products_index():
    return RedirectResponse("/#fragrances", status_code=302)

@app.get("/products/{slug}", response_class=HTMLResponse)
async def product_detail(request: Request, slug: str):
    product = PRODUCTS.get(slug)
    if not product:
        return HTMLResponse("Product not found", status_code=404)
    others = {k: v for k, v in PRODUCTS.items() if k != slug}
    return templates.TemplateResponse(request=request, name="products/detail.html", context={**get_context(), "product": product, "others": others})

@app.get("/story", response_class=HTMLResponse)
async def story(request: Request):
    return templates.TemplateResponse(request=request, name="story.html", context=get_context())

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

    # Recalculate from PRODUCTS dict (defense in depth — never trust client prices)
    items = json.loads(meta.get("items_json", "[]"))
    validated_items = []
    calculated_subtotal = 0
    for item in items:
        product = PRODUCTS.get(item.get("id"))
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

    # Validate items against PRODUCTS dict — never trust client prices
    validated_items = []
    calculated_subtotal = 0
    line_items = []

    for item in body.get("items", []):
        product = PRODUCTS.get(item.get("id"))
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
        "items_json": json.dumps(validated_items),
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

    # Validate product exists and use authoritative price
    product = PRODUCTS.get(product_id)
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
        # Validate product exists and use authoritative price
        product = PRODUCTS.get(pid)
        if not product:
            continue  # Skip unknown products silently during sync
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
