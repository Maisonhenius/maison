# Maison Henius

Luxury niche perfume house. FastAPI + Hotwire (Turbo/Stimulus) + Supabase.

> **Companion docs** (read on demand — NOT auto-loaded):
> - `docs/DEPLOY.md` — Railway redeploy recipe, custom-domain DNS, broken-CLI workaround
> - `docs/MEDIA.md` — scroll-cinematic architecture, image size targets, cwebp/ffmpeg recipes
> - `docs/NANO-BANANA.md` — image-editing workflow + AI-edited asset inventory

## Project

- FastAPI backend with Jinja2 templates, Hotwire (Turbo Drive + Stimulus)
- Supabase for auth (customer email/password + admin magic link), database, and realtime
- Serve locally: `cd server && uvicorn app:app --reload --port 3000`
- Install deps: `cd server && pip install -r requirements.txt`
- Stripe local testing: `stripe listen --forward-to localhost:3000/api/stripe/webhook` (separate terminal)
- Env vars in `.env.local` (gitignored) - Supabase URL, keys, DB password, Stripe keys + webhook secret, RESEND_API_KEY
- Brand bible lives in `BRAND.md` - read it before writing any copy
- Canva reference site has richer fragrance content: https://maisonhenius.my.canva.site/fragrances

## Architecture

```
server/
  app.py                  <- FastAPI app, all routes + API endpoints
  email_service.py        <- Resend SDK: branded transactional emails (auth + order status notifications)
  requirements.txt        <- gitignored (local dev with test deps); deploy uses root requirements.txt
  tests/                  <- gitignored, local only
    conftest.py           <- Shared fixtures (async client). Lazy-imports app inside fixture.
    test_email.py / test_routes.py / test_stripe.py
  templates/
    layout.html           <- base template (nav, footer, Hotwire importmap, CDN scripts)
    index.html            <- landing page (extends layout)
    products/detail.html  <- single product template (data from route param, serves all 5)
    story.html            <- Our Story / Universe page (centered text + image sections)
    terms.html / privacy.html  <- legal pages (extend layout, `.legal-*` CSS)
    cart.html             <- Cart page (MaisonCart localStorage)
    checkout.html         <- Checkout (requires login, creates Stripe Checkout Session)
    checkout-success.html <- Order confirmation after Stripe payment
    profile.html          <- User profile (fetches from /api/profile)
    login.html / signup.html / forgot-password.html / reset-password.html  <- customer auth (standalone, no layout)
    admin/
      layout.html         <- Admin base (sidebar nav, auth guard via JS)
      login.html          <- Admin magic link auth (standalone)
      auth-callback.html  <- Magic link redirect handler (extracts token, stores, redirects)
      dashboard.html      <- Stats + recent orders (from /api/admin/stats)
      orders.html         <- Orders list: search, date filter, expandable rows, status update + email
      products.html       <- DB-backed products list: thumbnails, hide/show toggle, edit/delete
      product_form.html   <- Create + edit (mode=create|edit); image+video upload widgets
      content.html / content_edit.html  <- CMS overview + per-page PAGE_CONTENT_SCHEMA editor
      messages.html       <- Messages list + read/unread (from /api/admin/messages)
    shop.html             <- /shop e-commerce grid (dark theme, filter chips, sort dropdown)
  migrations/             <- Schema + seed scripts (run via `python migrations/run_migration.py <file.sql>`)

# Root-level files (outside server/)
requirements.txt          <- Production deps (committed). Used by Railway/Docker build
Procfile                  <- Start command for Railpack/Procfile builder
.env.local                <- SUPABASE_URL/ANON_KEY/SERVICE_ROLE_KEY, DATABASE_URL, STRIPE_* keys + webhook secret, RESEND_API_KEY
js/application.js         <- Turbo + Stimulus init, GSAP/Lenis lifecycle on turbo events
js/cart.js                <- MaisonCart module (localStorage + Supabase sync when logged in)
css/style.css             <- Shared public styles (nav, footer, typography, reset, mobile nav)
admin/admin.css           <- Shared admin styles (sidebar, layout, responsive)
BRAND.md                  <- Brand strategy, tone, visual identity, collection details
assets/
  images/logo.svg         <- Gold monogram logo (#E9DB90)
  videos/web/             <- Web-optimized videos: brand-film-silent.{mp4,webm} + brand-film-audio.m4a (hero) + scroll-cinematic.mp4
  pictures/               <- Product photography, landscapes, olfactory pyramids
  pictures/ingredients/   <- 32 ingredient WebP photos (800px, ~170KB each). 4K PNG originals gitignored
```

## Async DB Helpers (MUST USE for all DB code)

`supabase-py` is **synchronous**. Calling `.execute()` directly in an `async def` route blocks
the asyncio event loop for the whole round-trip (~100–400ms), starving every other request.
Every Supabase call in `app.py` is wrapped in one of two thread-offload helpers:

```python
async def _db(query):                                # for builder chains
    return await asyncio.to_thread(query.execute)

async def _to_thread(callable_, *args, **kwargs):    # for auth / stripe / email / ad-hoc
    return await asyncio.to_thread(callable_, *args, **kwargs)
```

Patterns:
```python
result = await _db(supabase.table("orders").select("*").eq("id", x))        # NOT .execute() directly
user   = await _to_thread(supabase.auth.get_user, token)                    # auth/stripe/resend
await _db(supabase.table("order_items").insert(rows))                       # batch list insert, NOT a loop
profile, addresses, orders = await asyncio.gather(...)                      # parallelize independent reads
```

- **Batch inserts over loops** — `supabase-py` accepts a list to `.insert()`. Avoid N+1 round-trips.
- **Parallelize independent reads** with `asyncio.gather` (done in `/api/profile`, `/api/admin/stats`).
- **Both `get_authenticated_user()` and `get_admin_user()` are `async`** — callers must `await` them.

## Auth System

- **Customer**: email/password via Supabase Auth (`/login`, `/signup`). API `POST /api/auth/login|signup`. Token in `localStorage['maison_auth']`.
- **Admin**: magic link (`/admin/login`), restricted to `osamah96@gmail.com`, `husein.aldarawish@gmail.com`. API `POST /api/admin/auth/send-link`. Token in `localStorage['maison_admin_auth']`. All `/api/admin/*` check it via `get_admin_user()`.
- Nav profile icon → `/profile` when logged in, `/login` when not.
- **Magic-link redirect allowlist (silent-fail trap)**: `send-link` / forgot-password build `redirect_to` from the live `host` header, so EVERY auth-serving domain (canonical `www.maisonhenius.com`) must have its callback paths on the Supabase Redirect URLs allowlist (Auth > URL Configuration). A `redirect_to` not on the list does NOT error — Supabase silently falls back to the Site URL, dumping the user on the home page instead of `/admin/auth/callback`. Fixed with wildcards `https://www.maisonhenius.com/**` + `https://maisonhenius.com/**`; Site URL = `https://www.maisonhenius.com/`.
- **Checkout requires login**: `/checkout` → `/login?redirect=/checkout` if not authed. Login/signup pass `?redirect=` between each other.
- **Stripe Checkout**: Checkout → Stripe Checkout Session → hosted page → webhook creates order on success → `/checkout/success`.

## API Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/terms`, `/privacy` | GET | None | Legal pages |
| `/api/auth/login` | POST | None | Customer login |
| `/api/auth/signup` | POST | None | Customer registration + profile creation |
| `/api/auth/forgot-password` | POST | None | Send password reset email |
| `/api/auth/reset-password` | POST | None | Update password (requires reset token) |
| `/api/checkout/create-session` | POST | Bearer | Create Stripe Checkout Session — validates items server-side, returns redirect URL |
| `/api/stripe/webhook` | POST | Stripe Sig | Handle events (checkout.session.completed → create order, clear cart) |
| `/checkout/success` | GET | None | Order confirmation after Stripe payment (self-healing) |
| `/api/messages` | POST | None | Submit contact form message |
| `/api/profile` | GET/PATCH | Bearer | Profile + addresses + orders / update full_name, phone |
| `/api/admin/auth/send-link` | POST | None | Send admin magic link (whitelist check) |
| `/admin/auth/callback` | GET | None | Handle magic link redirect (extracts token client-side) |
| `/api/admin/stats` | GET | Admin | Dashboard stats (order count, revenue, messages) |
| `/api/admin/orders` | GET | Admin | List most-recent 500 orders (capped) |
| `/api/admin/orders/{id}` | PATCH | Admin | Update status + send customer email (shipped/delivered/cancelled) |
| `/api/admin/messages` | GET | Admin | List most-recent 500 messages (capped) |
| `/api/admin/messages/{id}/read` | PATCH | Admin | Mark message as read |
| `/api/profile/addresses` | POST | Bearer | Create address |
| `/api/profile/addresses/{id}` | PATCH/DELETE | Bearer | Update / delete address |
| `/api/profile/addresses/{id}/default` | PATCH | Bearer | Set default address |
| `/api/cart` | GET/POST | Bearer | Get cart / add item |
| `/api/cart/{id}` | PATCH/DELETE | Bearer | Update quantity / remove item |
| `/api/cart/sync` | POST | Bearer | Merge localStorage cart with server on login |

## Supabase Database

Tables: `profiles`, `addresses`, `orders`, `order_items`, `messages`, `cart_items`. All RLS-enabled.
- **profiles**: id (uuid), full_name, email, phone, created_at, updated_at
- **addresses**: id, user_id, full_name, phone, line1, line2, city, state, postal_code, country, is_default, created_at
- **orders**: id (text MH-*), user_id, customer_name/email/phone, shipping_address (jsonb), items (jsonb), subtotal, shipping, total, status, stripe_session_id, created_at
- **order_items**: id, order_id (FK→orders), product_id, product_name, product_family, price, quantity, line_total (generated), created_at — for analytics (best sellers, revenue/product)
- **cart_items**: id, user_id, product_id, product_name, product_family, product_price, product_image, quantity, created_at

## Hotwire Integration

- **Turbo Drive**: SPA-like nav (intercepts links, swaps body). **Stimulus**: JS controllers w/ `connect()`/`disconnect()`. **Import maps**: CDN Turbo + Stimulus (no bundler).
- **GSAP/Lenis lifecycle**: killed on `turbo:before-render`, reinited on `turbo:load`. Inline listeners use the guard IIFE pattern (see Gotchas).
- **Lenis ticker cleanup**: `turbo:before-render` must remove the GSAP ticker callback BEFORE destroying Lenis, or `null.raf()` crashes the page.
- `layout.html` is the single source of truth for nav + footer on all public pages.

## Brand Rules

- **Read `BRAND.md` before any copy, color, or design decision.**
- Colors: Black `#0a0a08`, Ivory `#faf9f6`, Gold `#e9db90`/`#b8a44e`, White `#fff`
- Fonts: Cormorant Garamond (headings, weight 300, italic), Montserrat (body, weight 300)
- Tone: Narrative, poetic, confidently minimal. Never religious, trendy, or mass-market.
- Footer copyright: "Maison Henius" (brand name). Legal entity "Marisal Goods wholesalers -FZE" is used ONLY in legal docs, never in visible UI.

## Design Context

Before any frontend/design work, read these root files (generated via `/impeccable teach`; the `/impeccable` skill auto-loads them):
- **`PRODUCT.md`** — strategic source of truth. Register `brand` (design IS the product; cinematic storytelling leads, commerce serves). Users, purpose, brand personality, anti-references (no mass-market retail / hype-drop culture / baroque heavy-luxury), 5 design principles.
- **`DESIGN.md`** + **`DESIGN.json`** — visual system (Google Stitch format). North Star **"The Amber Hour."** Palette (Desert Ink `#0a0a08`, Imperial Gold `#e9db90`, Antique Gold `#b8a44e`, Atelier Ivory `#faf9f6`, Warm Sand `#f5f0e8`, Canyon Ochre `#d4614b`), type scale, two button languages (solid-gold commerce CTA + ghost-to-fill editorial), borderless-line inputs, gold divider, named rules (Glow, No-Pure-Black, Wide-Tracking, Warm-Shadow).

`BRAND.md` is the prose brand bible; PRODUCT.md/DESIGN.md are the machine-readable contract derived from it.

## Mobile / Responsive

Mobile-first. Tested viewports: 320×568 (iPhone SE worst case), 375×812, 768 (iPad portrait) — verify with Playwright before claiming a mobile fix done.
- **iOS auto-zoom prevention**: global `@media (max-width: 768px) { input, select, textarea { font-size: 16px !important } }` in `style.css`. iOS Safari force-zooms 1.5x on inputs < 16px — the `!important` is intentional, do NOT remove. The 4 standalone auth pages inline their own copy on `.auth__input` (they don't load `style.css`) — keep all in sync.
- **iOS `100dvh` pattern**: every `100vh` is paired with a `100dvh` override on the next line (`height: 100vh; height: 100dvh;`). iOS Safari's `100vh` is the LARGE viewport (toolbar collapsed) so content gets cut off; `100dvh` adjusts in real-time. Applied across index/story/cart/checkout/auth/admin. ALWAYS use this for new full-height containers.
- **Touch targets ≥ 44×44 px** (WCAG 2.5.5 + Apple HIG): nav icons, hamburger, cart qty buttons, auth submit (`min-height: 48px`), profile address actions (negative-margin trick), product hero CTA (full-width mobile).
- **Never `100vw` for full-bleed** — it includes scrollbar width and overflows. Use `width: 100%`. `body { overflow-x: hidden }` is the global safety net. Never add `user-scalable=no`.
- **Global `img { border-radius: 12px }`**: full-bleed images (`.product-mood__img`, `.story-hero__img`, `.product-hero__media`) need explicit `border-radius: 0` to override. Check when adding any edge-to-edge image.
- **Hamburger nav < 768px**: nav switches flex → CSS grid (`grid-template-columns: 1fr auto 1fr`) to center logo regardless of side widths (hamburger `justify-self: start`, logo `center`, icons `end`).
- **Product hero CTA stacks vertically < 480px** (`.product-hero__bar` → column). Don't fit side-by-side at 320px.
- **Scroll-to-top FAB on all viewports** (44×44px). Watch for overlap with `/story` pillar text at narrow widths — add a selective per-page hide, not a global one.

## Animation Stack

- **GSAP 3.12 + ScrollTrigger** + **Lenis 1.1** (all CDN). Lenis connected to GSAP ticker.
- **No SplitText** — paid plugin, NOT on public CDN, crashes the script. Use clipPath mask reveals.
- **Hash anchors**: `application.js` intercepts `<a href="#...">` for Lenis smooth scroll. Must `ScrollTrigger.refresh()` before `lenis.scrollTo()` (pin spacer heights). Cross-page hash links handled in `turbo:load` with a 300ms delay.
- **Lenis cleanup is defensive** — `lenis.destroy()` / `gsap.ticker.remove()` / `ScrollTrigger.kill()` all try/catch-wrapped in `application.js`, run on `turbo:before-render` AND start of `turbo:load` (idempotent).
- **Global error logger** (`application.js`): `window.error` + `unhandledrejection` log as `[maison] uncaught error: ...`. Check console for these tags first when a page freezes.
- **Scroll cinematic = `<video>` + `currentTime` scrub, NOT canvas + frames** (see Gotchas + `docs/MEDIA.md`).

## Testing

**Tests are gitignored** (`server/tests/`, `server/requirements.txt`, `server/pytest.ini`, `server/TESTING.md`) — local-only to keep the deploy repo lean. Fresh clones don't have them; re-add via `git rm --cached`.
- Run: `cd server && python3 -m pytest tests/ -v`. Framework: pytest + pytest-asyncio + httpx.
- 100% coverage goal — write tests for new functions, bug fixes, conditionals.
- **Harness skips startup events**: httpx `ASGITransport` doesn't run FastAPI lifespan, so `_PRODUCTS_CACHE` is empty and product routes 404. The `client` fixture populates it via `await app.reload_products_cache()` before yielding. Required for product-dependent tests.

## Browser Testing

- **Always use Playwright** MCP tools, never Chrome MCP. Delegate Playwright to a subagent via the Agent tool — never run it directly in the main session.
- **Quick visual checks**: don't spawn agents. Ensure the dev server is running and tell the user which URL to check in their own browser. Playwright only for comprehensive automated testing or when explicitly requested.

## Gotchas

### Dev / data
- **Dev server**: `cd server && uvicorn app:app --reload --port 3000`. NOT `npx serve` / `python3 -m http.server`. `.env.local` must exist at project root (loaded via python-dotenv).
- **`--reload` only watches Python files** — DB-only changes (seeded row, data migration) don't reload `_PRODUCTS_CACHE`. Touch `app.py`, restart, or trigger an admin mutation that calls `reload_products_cache()`.
- **`psql` is NOT installed locally**. Schema migrations: `cd server && python migrations/run_migration.py <name.sql>` (psycopg2 + `DATABASE_URL`). Data migrations are standalone Python scripts using `supabase-py` + service role key (see `002_seed_products.py`, `008_*.py`). **The Supabase MCP server is NOT connected to Maison** (linked account only exposes unrelated `halulu` projects) — for ad-hoc DB reads/writes use a `psycopg2` + `DATABASE_URL` one-liner, never the `mcp__*Supabase*` tools.
- **Product data** lives in Supabase `products`, loaded into `_PRODUCTS_CACHE` at startup. Use `get_product(id)` / `get_products_dict()` / `await reload_products_cache()` — never read the cache directly. Every admin mutation auto-invalidates it.
- **Server-side price validation**: all purchase paths validate via `get_product(id)` (rejects hidden products). Pass `include_hidden=True` ONLY when reconstructing a paid order in the Stripe webhook fallback.
- **"PRODUCTS dict" is gone** — any stale doc/commit saying so refers to pre-migration-001 code. It's now a DB row mapped by `_row_to_product()` to the same shape.
- **Product image filenames** `Velvet Waterfall .png` and `Oud Passion .png` have trailing spaces — URL-encode as `%20`.
- **Static files** mounted as 4 separate dirs (`/static/{css,js,assets,admin}`) — never exposes project root. Root files (favicon) via whitelist route.

### Admin auth
- **`localStorage["maison_admin_auth"]` is JSON-stringified, NOT a raw token** (trap: silent 401s). Auth-callback stores `JSON.stringify({access_token,...})`. Every admin page MUST `JSON.parse(auth).access_token` before sending it as a Bearer header. Working pattern in `admin/dashboard.html`; mirror it on every new admin page.
- **Admin pages must auto-redirect to `/admin/login` on 401** — Supabase JWTs expire ~1h. Detect `r.status === 401`, clear the localStorage key, `window.location.href = '/admin/login'`. Otherwise the page sits on "Failed to load (status 401)" forever.
- **Admin auth guard**: `admin/layout.html` JS checks `maison_admin_auth` and redirects before render.
- **Headless admin auth for tests**: mint a one-shot magic link via `supabase.auth.admin.generate_link({"type":"magiclink","email":"osamah96@gmail.com","options":{"redirect_to":".../admin/auth/callback"}})`, navigate to it (stores token in localStorage). Single-use, ~1h TTL; `error=otp_expired` → regenerate.

### Turbo / JS lifecycle
- **`turbo:load` listeners need TWO guards** (trap: real bugs, not just warnings):
  1. **IIFE guard** (per JS load): `(function(){ if(window._pageInitBound) return; window._pageInitBound=true; document.addEventListener('turbo:load', ...); })()` — registers once, no accumulation.
  2. **Page-presence guard** (per fire): `if (!document.querySelector('.unique-page-element')) return;` as FIRST line. Without it the listener fires on EVERY navigation (e.g. `profile.html` was force-redirecting logged-out users to `/login` on every nav). Sentinels: landing `.hero__video`, story `.story-hero`, profile `#addressList`, product `.product-hero`, cart `#cartItems`, checkout `#checkoutForm`. Animation pages also need `requestAnimationFrame` wrapping + `ScrollTrigger.refresh()` at end.
- **Standalone pages + Turbo** (login, signup, forgot/reset-password, admin/login, admin/auth-callback don't extend `layout.html`): links to them MUST have `data-turbo="false"` — else Turbo SPA-navigates, corrupts GSAP state, back-nav shows blank. They also don't load `style.css`, so global mobile rules (iOS-zoom, touch targets) must be DUPLICATED into each one's inline `<style>` — keep in sync.
- **Mobile nav double-init**: `initMobileNav()` runs immediately AND on `turbo:load`; the `dataset.mobileNavInit` guard prevents duplicate listeners. Do NOT remove it.
- **Landing nav lives in THREE places** — `index.html` overrides `{% block nav %}` with its own hero header. Nav changes must mirror: `layout.html` nav, `index.html` hero nav, AND the `#mobileNav` overlay in `layout.html`.
- **`application.js` cache-busting**: bump the `?v=N` in `layout.html` after editing (browser caches the ES module hard). `style.css` cache-bust is at **`?v=8`** — bump when editing it.
- **`cart.js` is global** (loaded in `layout.html`); `MaisonCart` is on every page.
- **ScrollTrigger pin vs CSS sticky**: scroll-video uses `position: relative` — ScrollTrigger handles pinning.

### Scroll cinematic (full architecture in `docs/MEDIA.md`)
- **Uses native `<video>` + `currentTime` scrub, NOT canvas + ImageBitmap. DON'T revert.** The old canvas approach preloaded 121 WebP frames as ImageBitmaps (~1 GB RGBA) and OOM-crashed every iOS Safari tab. The video pipeline caps at ~30 MB. If smoothness regresses, debug the `requestAnimationFrame` coalescing in `applyScrub` — don't swap back to frames.
- **ScrollTrigger MUST be created synchronously**, not gated on `loadedmetadata` (a starved video means the section never pins). **Prime the video** via `play().then(()=>{pause(); currentTime=0.001})` through an IntersectionObserver — iOS won't render `currentTime` on a paused video that never played. **Don't add high-priority `<link rel=preload as=video>` for both hero AND scroll-cinematic** — the preload scanner starves one.

### Video / images
- **Hero video is SILENT + separate `<audio>` toggle. Don't merge audio back into the video.** macOS Safari blocks autoplay of any video with an audio track (even `muted`). `brand-film-silent.{mp4,webm}` (autoplays) + `brand-film-audio.m4a` (toggle). MP4 source FIRST so Safari grabs H.264. Full reasoning + the `.m4a` MIME registration in `docs/MEDIA.md`.
- **Always check image dimensions before encoding** — `cwebp` doesn't auto-resize; forget `-resize WIDTH 0` and you ship a 4K image at 600px (~1 MB wasted/file). Recipes + size targets in `docs/MEDIA.md`.
- **Square images — NEVER use `aspect-ratio`** (breaks in flex/inline-block/with HTML w/h attrs; has failed repeatedly). Use explicit equal `width`+`height` on container + `overflow:hidden`, then `width:100%;height:100%;object-fit:cover` on `<img>` (remove HTML w/h attrs). In CSS grid use the padding-bottom trick: `padding-bottom:100%;position:relative;overflow:hidden` on wrapper + `position:absolute;inset:0;...object-fit:cover` on img (what `.product-explore__card-img` uses).
- **Three product image sections are INDEPENDENT — always ask which before swapping**: (1) landing collection cards `card_image`, (2) product Explore More `card_image`, (3) product Mood section `mood_image`. Changing one ≠ changing the others.
- **Ingredient changes touch THREE assets**: ingredient image in `ingredients/`, bottle hero `bottle-{slug}.webp`, AND card `card-{slug}.webp`. Miss one → old ingredient still visible.
- **Shared ingredient images need copies, not renames**: `rose.webp` etc. are reused across products. To rename the display for ONE product, copy `rose.webp` → `moldavian-rose.webp` and update only that product's `images` array. Template renders display names from filenames via `{{ img | replace('-',' ') | title }}`.
- **`.product-bottle__img` uses `box-shadow` + `border-radius`, NOT `filter: drop-shadow`** — bottle heroes are full-frame photos with their own cream backdrop. If you swap back to cutout PNGs, revert to `filter: drop-shadow(...)` (box-shadow on a cutout renders a rectangular halo). Width `clamp(280px,42vw,480px)`.
- **Product explore cards**: name is a separate `<span>` below the `.product-explore__card-img` wrapper, NOT overlaid. Don't add gradient overlays.
- **GSAP `fromTo` + lazy images flicker**: don't `gsap.fromTo(img,{opacity:0},{opacity:1})` on `loading="lazy"`/`decoding="async"` images (browser shows it, GSAP hides then re-animates → flicker). Set `opacity:0` in CSS, remove `loading="lazy"`, use `gsap.to()`. Applied on `.product-bottle__img`.
- **Hard refresh after in-place image swaps** — assets have 30-day `Cache-Control`. Warn the user to Cmd+Shift+R / use incognito.
- **Recovering overwritten images from git**: `git show COMMIT:'assets/.../file.webp' > new-name.webp` (find commit via `git log --oneline --follow -- path`). Save with a DISTINCT name — never overwrite before confirming.
- **Product hero is ONE media field** — `products.video` holds EITHER image OR video URL. `products/detail.html` renders `<video>` (ext `.mp4/.webm/.mov/.m4v`) or `<img>` via the `is_video_url()` Jinja global; empty → black bg. Hero class `.product-hero__media` (carries `border-radius:0`).

### Stripe / orders / cart
- **Webhook raw body**: `/api/stripe/webhook` must read `await request.body()` (raw bytes) for signature verification — parsed JSON breaks the check.
- **StripeObject metadata**: `Webhook.construct_event()` returns `StripeObject`; `session.metadata` has no `.get()` — `.to_dict()` first.
- **Metadata value cap = 500 chars**: `items_json` stores only `id` + `quantity` per item (name/family/price re-validated from the products cache in the fallback). 5 products at full verbosity hit 522 chars and broke checkout.
- **Jinja2 `order.items` collision**: `order.items` resolves to `dict.items()`, not the `"items"` key. Use `order['items']` bracket notation.
- **Order status flow**: `create-session` pre-creates `status="pending"` (abandoned-checkout: full customer info, payment incomplete). On payment, `_create_order_from_stripe_session()` → `_confirm_order()` transitions `pending → confirmed`, inserts `order_items`, clears server cart. Statuses: `pending, confirmed, shipped, delivered, cancelled`. shipped/delivered/cancelled auto-send a branded email; pending/confirmed don't.
- **`pending` excluded from revenue/total_orders stats** — `/api/admin/stats` uses `PAID_STATUSES={confirmed,shipped,delivered}`, exposes a separate `pending_orders` count. Cancelled also excluded from revenue.
- **Don't insert `order_items` or clear `cart_items` on pre-create** — only on `pending → confirmed` (in `_confirm_order`). Else abandoned checkouts pollute analytics / the user can't retry.
- **`/checkout/success` is self-healing** — verifies the Stripe session via API then calls `_create_order_from_stripe_session()` (same helper as the webhook), idempotent via existing-order check. Change the HELPER, not the webhook handler — both flow through it.
- **First checkout auto-saves to profile** — `create-session` inserts the typed address (`is_default=true`) if the user has zero saved addresses. Try/except so a save failure doesn't block payment. Trigger: `address.line1 AND address.city` present.
- **Postal code conditionally required**: `checkout.html` `REQUIRES_POSTAL = {US,GB,FR,DE}` only (Gulf countries optional). `syncPostalRequired()` toggles `required` + the `(optional)` hint. Adding a country → decide if it belongs in the set.
- **Cart sync is server-authoritative for logged-in users** — `loadFromServer()` always overwrites localStorage (empty included). DON'T add merge logic here (caused the "stale cart after checkout" bug); guest→login merge lives in `sync()`, called from `login.html`.
- **`loadFromServer()` skips on `/checkout/success`** (guard at top) — removing it re-introduces a race where the in-flight fetch repopulates localStorage after the page clears it.
- **`cart.js` evicts stale tokens on 401** — removes `maison_auth` from localStorage. Don't replace with a retry loop; the token is dead.
- **`cart.js` items include `serverId`** (not just product `id`) — lets logged-in mutations go in 1 round-trip instead of 2. Legacy items without it fall back via `_findServerItemId()`. Don't strip it.

### Server / middleware / email
- **Don't change middleware order in `app.py`** — `CacheControlMiddleware` added BEFORE `GZipMiddleware`. Starlette runs `add_middleware()` in reverse on responses, so GZip wraps CacheControl and `Vary: Accept-Encoding` lands after the cache headers.
- **`CacheControlMiddleware` MUST skip 4xx/5xx** — it sets `max-age=2592000` on static assets by PATH; without the status guard (`app.py:~100`, `if not 200 <= status < 300: return response`) it caches a 404 for 30 days, poisoning the client cache even after you add the asset. 2xx (incl. 206 range responses) still cached.
- **Resend emails**: signup confirm / password reset / admin login sent via Resend from `noreply@maisonhenius.com`. Routes use `supabase.auth.admin.generate_link()` (service role) for verification URLs, then `email_service.py` delivers branded HTML. Exception: reset-password creates its own anon client (isolated `set_session()`). Module is `email_service.py` (not `email.py`) to dodge the stdlib conflict.

### CSS / layout
- **Footer has three rows**: `.footer__social` (Instagram/TikTok) → `.footer__links` (Terms/Privacy) → `.footer__legal` (copyright). New footer links go in `.footer__links`.
- **Legal pages share `.legal-*` CSS** (terms + privacy define identical inline `.legal-hero`/`.legal-body`/`.legal-section`). Copy the class system for any new legal page. `signup.html` `.auth__agree` links to `/terms` + `/privacy`.
- **Pseudo-element overflow on mobile**: `.story-craft__image::before` (`inset:-10% -5%` gold halo) bleeds past the viewport; `.story-craft` gets `overflow:hidden` < 768px. Check decorative `::before`/`::after` with negative inset.
- **Cart badge offset on mobile**: `.nav__cart` mobile `padding:13px` shifts the absolute `.cart-badge`; the mobile breakpoint overrides it to `top:2px; right:0px`. Recalc if you change the padding.

## Assets (images & video)

Repo images are WebP (PNG/JPG originals gitignored). Size targets + cwebp/ffmpeg recipes + the full tracked-vs-gitignored lists live in `docs/MEDIA.md`.

- **`products` table has 4 image fields**: `card_image` (square 1200², landing collection + product Explore More), `mood_image` (landscape 1920×1072, product Mood section only), `bottle_image` (portrait 1200×1490, product "The Bottle" section), `explore_image` (legacy square variants, not currently referenced).
- **Fields hold EITHER a full URL OR a legacy bare filename. NEVER prepend a `/static/` path manually in a template — always resolve via the Jinja filter** (passes URLs through, prefixes only bare names):
  - `{{ p.card_image | product_image }}` → `/static/assets/pictures/Collection & Fragrances/`
  - `{{ slug | ingredient_image }}` → `/static/assets/pictures/ingredients/{slug}.webp`
  - `{{ p.video | product_video }}` → `/static/assets/videos/web/`
  - `{{ value | page_media }}` → `/static/assets/` (CMS images/videos)

  Migration 008 moved existing product media to Supabase Storage URLs; new admin uploads write there too.
- **Logotype**: `assets/images/logotype.webp` (800×873, alpha) — crest + "Maison Henius" + "Collection Eaux de Parfums"; used in footer + auth pages. Monogram SVG `assets/images/logo.svg` still used in nav + favicons.

## Performance

Three layers near the top of `server/app.py`:
1. **`mimetypes.add_type("image/webp", ".webp")`** (and `.m4a` → `audio/mp4`) at import, before any `StaticFiles` mount — the default Linux registry served WebP as `text/plain`.
2. **`CacheControlMiddleware`** by path: `/static/{css,js,admin}/*` → `max-age=31536000, immutable` (cache-busted via `?v=N`); `/static/assets/*` → `max-age=2592000` (30d); `/static/*` root → `max-age=86400` (1d). HTML + API get NO cache header.
3. **`GZipMiddleware(minimum_size=500)`** — ~70-80% on HTML/CSS/JS/JSON.

- **All Supabase/Stripe/Resend calls offloaded to worker threads** (`_db`/`_to_thread`); independent reads parallelized with `asyncio.gather` (`/api/profile`, `/api/admin/stats`). Admin lists capped at 500 rows.
- **Railway edge (Fastly) is passthrough, NOT a cache** — every response is `x-cache: MISS`. Don't try to "fix" it via headers; it's platform-level. Wins come from BROWSER caching (returning visitors / within-session nav hit local cache). Real multi-user edge caching needs **Cloudflare in front of Railway** (also flattens the apex CNAME).
- **Lighthouse baseline (2026-04-14)**: A11y / Best Practices / SEO = 100, LCP ~1.1s, CLS 0.00. Only remaining lever is TTFB via Cloudflare CDN.

## Admin CMS + Supabase Storage

- **Content CMS** edits `page_content` (one row per (page, section, field)). Schema = `PAGE_CONTENT_SCHEMA` dict in `app.py`. Add an editable block: append a schema entry, reference it in the template via `{{ content('section','field','fallback') }}` — the editor picks it up next load.
- **`content()` helper** is injected into `/` and `/story` contexts ONLY. Returns saved value, falls back to the inline string. Filter chain works: `{{ content('hero','image','...') | page_media }}`.
- **Every-page content uses a Jinja GLOBAL, not `content()`** (footer/nav render everywhere but `content()` is only on `/` + `/story`). Footer social via `templates.env.globals["footer_social"]` ← `_FOOTER_SOCIAL` cache (`reload_footer_social()` merges saved rows over schema defaults; refreshed at startup + every `PUT /api/admin/content/main`). Edited at `/admin/content/main` section `footer`; `layout.html` renders a link only when visible AND has a URL.
- **Field types**: `text`, `longtext`, `image`, `video`, `toggle` (checkbox storing `"true"`/`"false"`). `content_edit.html renderField` handles each; save collector reads `checkbox.checked` for toggles. Editor prefills from schema `default` (`b.value || b.default`) so new entries show without a seed row.
- **Single source of truth**: page_content rows ARE the content (no default-vs-saved UI). Migrations 006/007 seeded + backfilled. Schema `default` strings still back template fallbacks.
- **Required fields**: schema `"required": True` renders a red `*` + HTML `required`/`aria-required`. Every text/longtext is required; image/video stay optional.
- **Two Storage buckets** (migration 003, public-read RLS): `product-images` (10 MB, image/webp+jpeg+png, path `products/{slug}/{filename}`); `page-media` (50 MB, images + video/mp4+webm, path `defaults/{name}` or `{stem}-{uuid8}{ext}`).
- **Storage upload signature** (supabase-py 2.x): `c.storage.from_(bucket).upload(path, bytes, {"content-type":"image/webp","cache-control":"..."})` — third arg is a positional `file_options` dict, keys **kebab-case** (`content-type`, NOT `contentType`). Wrap in `await _to_thread(...)`.
- **PostgREST upsert only writes columns in the payload** — the Content save handler omits `display_order` so rows keep seeded ordering; re-adding it causes silent drift on every save (fixed in `9373160`).
- **Products CRUD**: `/admin/products` (list), `/new`, `/{id}/edit`. Hide via `PATCH /api/admin/products/{id}/visibility`. Delete is blocked when the product has `order_items` rows — use Hide. Cache invalidates on every mutation.

## Stock / Inventory

- `products.stock` (int, NOT NULL, CHECK >= 0). **Never shown to customers** — templates use the derived `in_stock` boolean; cart API returns only `at_max`/`in_stock`, never the number.
- **Decrement on payment** via `_decrement_stock_for_items()` from `_confirm_order()` + the Stripe fallback. Never on pre-create. Idempotent via the status guard.
- **Atomic SQL** (migration 009): `decrement_stock(id,qty)` = `UPDATE ... SET stock=stock-qty WHERE stock>=qty RETURNING stock` (NULL if insufficient); `restock(id,qty)` adds back. Single-statement = concurrent buyers can't both take the last unit.
- **Oversell** (paid but raced to 0): never reject — clamp to 0, log `⚠ OVERSELL`. Payment always wins.
- **Restock on cancel**: `update_order_status` reads prior status first; restocks only when cancelling FROM confirmed/shipped/delivered (skips pending + already-cancelled → no double-restock).
- **Four anti-oversell gates**: product Add-to-Cart, cart `+` stepper (`at_max` disables), `/api/cart` add/update clamp, `create-session` hard-reject (409, no number in the message).
- Out-of-stock products STAY VISIBLE with an "Out of Stock" badge + disabled CTA. `_row_to_product` exposes `stock`+`in_stock`; product form has a required Stock field; `/admin/products` shows a Stock column (amber ≤5, red 0). `cart.js` carries `at_max`/`in_stock` into localStorage + fires `maison:cart-synced` so the cart re-renders on a server clamp.

## Stripe (current state)

- **Pre-launch checkout gate**: `CHECKOUT_COMING_SOON` constant in `app.py` (single source of truth). While `True`, `/checkout`'s "Continue to Payment" opens an "Arriving Soon" modal (gated by `{% if coming_soon %}` + `var COMING_SOON`) instead of redirecting to Stripe, AND `create_checkout_session` short-circuits with `{"coming_soon": true}` so a direct API hit can't pay. Flip to `False` + redeploy to enable real checkout. (Checkout requires login → registered users are the launch notify-list.)
- **Test mode active in production** (test keys in Railway env).
- **Webhook not yet configured on prod** — `STRIPE_WEBHOOK_SECRET=whsec_placeholder`. System still works because `/checkout/success` is self-healing. Configuring it is recommended for instant order creation + other events.
- **Local testing**: `stripe listen --forward-to localhost:3000/api/stripe/webhook`. Local secret in `.env.local`.

## Deployment (Railway) — full recipe in `docs/DEPLOY.md`

- **Live**: canonical `https://www.maisonhenius.com` (also `web-production-cc74a0.up.railway.app`).
- **Repo**: https://github.com/Maisonhenius/maison (public, lean ~46MB). **Builder**: Dockerfile (clones from GitHub on Railway servers).
- **Railway**: project `maison-henius` (`f45a16f9-e777-4cce-abd1-dcd08c2ccb56`), service `web` (`d363d941-07c4-4383-b0a2-c12ebd5a8cbd`), env `production` (`b99a4d18-a9fc-4742-b874-c0b4d38e5ade`). Owner account: **husein.aldarawish@gmail.com** (for `railway login`).
- **Redeploy + the critical `ARG CACHEBUST` bump, custom-domain DNS, and the broken `railway domain` CLI workaround → `docs/DEPLOY.md`.**

### Still needed
- **Stripe webhook secret** (currently `whsec_placeholder`) — create the webhook in Stripe Dashboard → `/api/stripe/webhook`, paste the signing secret into Railway env.
- Replace the `https://maisonhenius.com/` placeholder in `index.html` `og:image`; add `sitemap.xml` + a proper 1200×630 `og:image`.

## Future

- **Turbo Frames**: cart badge, admin stats as independent frames. **Turbo Streams**: real-time admin via SSE. **Stimulus**: migrate inline scripts to controllers.
- **Re-enable CI** — `.github/workflows/test.yml` was removed (ran pytest from `server/`, but `server/tests/` + `server/requirements.txt` are gitignored). Re-adding needs either un-ignoring those or a workflow that hits the live URL post-deploy.
