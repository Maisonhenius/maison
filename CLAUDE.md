# Maison Henius

Luxury niche perfume house. FastAPI + Hotwire (Turbo/Stimulus) + Supabase.

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
    test_email.py         <- Email module tests (HTML builders + send functions)
    test_routes.py        <- Route/page response tests
    test_stripe.py        <- Stripe checkout + webhook tests
  templates/
    layout.html           <- base template (nav, footer, Hotwire importmap, CDN scripts)
    index.html            <- landing page (extends layout)
    products/detail.html  <- single product template (data from route param, serves all 5)
    story.html            <- Our Story / Universe page
    cart.html             <- Cart page (MaisonCart localStorage)
    checkout.html         <- Checkout (requires login, creates Stripe Checkout Session)
    checkout-success.html <- Order confirmation after Stripe payment
    profile.html          <- User profile (fetches from /api/profile)
    login.html            <- Customer email/password auth (standalone, no layout)
    signup.html           <- Customer registration (standalone, no layout)
    forgot-password.html  <- Password reset request (standalone, no layout)
    reset-password.html   <- New password form (standalone, receives token from email)
    admin/
      layout.html         <- Admin base (sidebar nav, auth guard via JS)
      login.html          <- Admin magic link auth (standalone)
      auth-callback.html  <- Magic link redirect handler (extracts token, stores, redirects)
      dashboard.html      <- Stats + recent orders (from /api/admin/stats)
      orders.html         <- Orders list with search, date filter, expandable detail rows, status update + email notification
      messages.html       <- Messages list + read/unread (from /api/admin/messages)

# Root-level files (outside server/)
requirements.txt          <- Production deps (committed). Used by Railway/Docker build
Procfile                  <- Start command for Railpack/Procfile builder
.env.local                <- SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, DATABASE_URL, STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_WEBHOOK_SECRET, RESEND_API_KEY
js/application.js         <- Turbo + Stimulus init, GSAP/Lenis lifecycle on turbo events
js/cart.js                <- MaisonCart module (localStorage + Supabase sync when logged in)
css/style.css             <- Shared public styles (nav, footer, typography, reset, mobile nav)
admin/admin.css           <- Shared admin styles (sidebar, layout, responsive)
BRAND.md                  <- Brand strategy, tone, visual identity, collection details
assets/
  images/logo.svg         <- Gold monogram logo (#E9DB90)
  music/music.mp3         <- Background audio loop (19s, 192kbps)
  videos/web/             <- Web-optimized hero videos (H.264, ~3MB each)
  video-frames/           <- Scroll video WebP frames (121 desktop, 121 mobile, gitignored)
  pictures/               <- Product photography, landscapes, olfactory pyramids
  pictures/ingredients/   <- 32 ingredient WebP photos (800px, ~170KB each). 4K PNG originals are gitignored
```

## Async DB Helpers (MUST USE for all DB code)

`supabase-py` is a **synchronous** library. Calling `.execute()` directly inside an
`async def` route blocks the asyncio event loop for the whole Supabase round-trip
(~100–400ms), preventing any other request from being served during that time.
Every Supabase call in `app.py` is wrapped in one of two thread-offload helpers
defined at the top of the file:

```python
async def _db(query):          # for builder chains
    return await asyncio.to_thread(query.execute)

async def _to_thread(callable_, *args, **kwargs):  # for auth / stripe / email / ad-hoc
    return await asyncio.to_thread(callable_, *args, **kwargs)
```

**The pattern** at every call site:

```python
# ❌ WRONG (blocks the event loop)
result = supabase.table("orders").select("*").eq("id", x).execute()

# ✅ RIGHT
result = await _db(supabase.table("orders").select("*").eq("id", x))

# ✅ Auth / Stripe / Resend
user = await _to_thread(supabase.auth.get_user, token)
session = await _to_thread(stripe_client.v1.checkout.sessions.create, params={...})
await _to_thread(email_service.send_signup_confirmation, email, link, name)
```

**Batch inserts over loops.** `supabase-py` accepts a list to `.insert()` — use it to
avoid N+1 round-trips:

```python
# ❌ N round-trips
for item in items:
    await _db(supabase.table("order_items").insert(item))

# ✅ 1 round-trip
rows = [build_row(item) for item in items]
if rows:
    await _db(supabase.table("order_items").insert(rows))
```

**Parallelize independent reads.** `/api/profile` and `/api/admin/stats` both fetch
multiple tables — use `asyncio.gather` to run them in parallel across worker threads:

```python
profile, addresses, orders = await asyncio.gather(
    _db(supabase.table("profiles").select("*").eq("id", uid).single()),
    _db(supabase.table("addresses").select("*").eq("user_id", uid)),
    _db(supabase.table("orders").select("*").eq("user_id", uid).order("created_at", desc=True)),
)
```

**Both `get_authenticated_user()` and `get_admin_user()` are `async`** — callers must
`await` them: `user = await get_authenticated_user(request)`.

## Auth System

- **Customer**: email/password via Supabase Auth (`/login`, `/signup`)
  - API: `POST /api/auth/login`, `POST /api/auth/signup`
  - Token stored in `localStorage['maison_auth']`
- **Admin**: magic link email (`/admin/login`) - restricted to 2 emails only
  - API: `POST /api/admin/auth/send-link`
  - Token stored in `localStorage['maison_admin_auth']`
  - Allowed: `osamah96@gmail.com`, `husein.aldarawish@gmail.com`
- All `/api/admin/*` routes check admin token via `get_admin_user()` helper in app.py
- Nav shows profile icon: links to `/profile` when logged in, `/login` when not
- **Checkout requires login**: `/checkout` redirects to `/login?redirect=/checkout` if not authenticated
- **Login/signup redirect**: Both pages accept `?redirect=` param and pass it between each other
- **Stripe Checkout**: Checkout creates a Stripe Checkout Session → redirects to Stripe's hosted page → webhook creates order on payment success → redirects to `/checkout/success`

## API Routes

| Route | Method | Auth | Purpose |
|-------|--------|------|---------|
| `/api/auth/login` | POST | None | Customer email/password login |
| `/api/auth/signup` | POST | None | Customer registration + profile creation |
| `/api/auth/forgot-password` | POST | None | Send password reset email |
| `/api/auth/reset-password` | POST | None | Update password (requires reset token) |
| `/api/checkout/create-session` | POST | Bearer | Create Stripe Checkout Session — validates items server-side, returns redirect URL |
| `/api/stripe/webhook` | POST | Stripe Sig | Handle Stripe events (checkout.session.completed → create order, clear cart) |
| `/checkout/success` | GET | None | Order confirmation page after Stripe payment |
| `/api/messages` | POST | None | Submit contact form message to Supabase |
| `/api/profile` | GET | Bearer | User profile + addresses + order history |
| `/api/profile` | PATCH | Bearer | Update profile (full_name, phone) |
| `/api/admin/auth/send-link` | POST | None | Send admin magic link (whitelist check) |
| `/admin/auth/callback` | GET | None | Handle magic link redirect (extracts token client-side) |
| `/api/admin/stats` | GET | Admin | Dashboard stats (order count, revenue, messages) |
| `/api/admin/orders` | GET | Admin | List most-recent 500 orders (capped) |
| `/api/admin/orders/{id}` | PATCH | Admin | Update order status + send customer email (shipped/delivered/cancelled) |
| `/api/admin/messages` | GET | Admin | List most-recent 500 messages (capped) |
| `/api/admin/messages/{id}/read` | PATCH | Admin | Mark message as read |
| `/api/profile/addresses` | POST | Bearer | Create saved address |
| `/api/profile/addresses/{id}` | PATCH | Bearer | Update address |
| `/api/profile/addresses/{id}` | DELETE | Bearer | Delete address |
| `/api/profile/addresses/{id}/default` | PATCH | Bearer | Set default address |
| `/api/cart` | GET | Bearer | Get user's server cart |
| `/api/cart` | POST | Bearer | Add item to cart |
| `/api/cart/{id}` | PATCH | Bearer | Update cart item quantity |
| `/api/cart/{id}` | DELETE | Bearer | Remove cart item |
| `/api/cart/sync` | POST | Bearer | Merge localStorage cart with server on login |

## Supabase Database

Tables: `profiles`, `addresses`, `orders`, `order_items`, `messages`, `cart_items`
All have RLS enabled. Key columns:
- **profiles**: id (uuid), full_name, email, phone, created_at, updated_at
- **addresses**: id (uuid), user_id, full_name, phone, line1, line2, city, state, postal_code, country, is_default, created_at
- **orders**: id (text MH-*), user_id, customer_name/email/phone, shipping_address (jsonb), items (jsonb), subtotal, shipping, total, status, stripe_session_id, created_at
- **order_items**: id (uuid), order_id (FK→orders), product_id, product_name, product_family, price, quantity, line_total (generated), created_at — for analytics queries (best sellers, revenue per product)
- **cart_items**: id (uuid), user_id, product_id, product_name, product_family, product_price, product_image, quantity, created_at

## Hotwire Integration

- **Turbo Drive**: SPA-like navigation (auto-intercepts links, swaps body)
- **Stimulus**: JS controllers with `connect()`/`disconnect()` lifecycle
- **Import maps**: CDN-loaded Turbo + Stimulus (no bundler)
- **GSAP/Lenis lifecycle**: Killed on `turbo:before-render`, reinited on `turbo:load`
- **Turbo:load pattern**: Inline listeners use the guard IIFE pattern (see Gotchas). Animation pages also need `requestAnimationFrame` wrapping and `ScrollTrigger.refresh()` at end.
- **Lenis ticker cleanup**: `turbo:before-render` must remove the GSAP ticker callback BEFORE destroying Lenis, or `null.raf()` errors crash the page.
- **Templates**: `layout.html` is the single source of truth for nav + footer on all public pages

## Brand Rules

- **Read `BRAND.md` before any copy, color, or design decision**
- Colors: Black `#0a0a08`, Ivory `#faf9f6`, Gold `#e9db90`/`#b8a44e`, White `#fff`
- Fonts: Cormorant Garamond (headings, weight 300, italic), Montserrat (body, weight 300)
- Tone: Narrative, poetic, confidently minimal. Never religious, trendy, or mass-market
- Visible copyright in footer: "Maison Henius" (brand name, per user direction 2026-04-08). Legal entity is still "Marisal Goods wholesalers -FZE" but only used in legal documents (Terms of Service, etc.), not in visible UI copy.

## Mobile / Responsive

Site is mobile-first. Key patterns to preserve:

- **iOS auto-zoom prevention**: `style.css` has a global `@media (max-width: 768px) { input, select, textarea { font-size: 16px !important } }` rule. iOS Safari force-zooms 1.5x on any input < 16px — the `!important` is intentional, do NOT remove. Auth pages (login/signup/forgot-password/reset-password) inline their own copy of this rule on `.auth__input` because they don't load `style.css` — keep all 4 in sync.
- **Touch targets ≥ 44×44 px** (WCAG 2.5.5 + Apple HIG). Currently enforced at: header nav icons, hamburger, cart qty buttons (`width: 44px; height: 44px` on mobile media query), auth submit buttons (`min-height: 48px`), profile address Edit/Delete actions (negative-margin trick to keep visible size small but tap area ~44px), product hero Add to Cart (full-width on mobile).
- **Viewport safety**: every page has `<meta name="viewport" content="width=device-width, initial-scale=1.0">`. Never add `user-scalable=no` (accessibility violation).
- **`body { overflow-x: hidden }`** is the global safety net against horizontal scroll. Any new section that needs full-bleed should use `width: 100%` (NOT `100vw` — `100vw` includes scrollbar width and overflows on desktop).
- **Hamburger nav < 768px**: `.nav__hamburger` shown, `.nav__left` hidden, `.nav__right` collapses gap. Logo flexes to center. Pattern lives in `style.css` `@media (max-width: 768px)`.
- **Scroll-to-top FAB hidden < 480px**: `.scroll-top { display: none }` on small screens. Was added because the FAB overlapped pillar descriptions on `/story` at narrow widths. JS still adds the `is-visible` class on scroll, but CSS overrides — pages are short enough on a phone that the FAB doesn't add value.
- **Product hero CTA stacks vertically < 480px**: `.product-hero__bar` becomes `flex-direction: column`, price + Add to Cart full-width. Don't try to fit them side-by-side — at 320px the price gets crushed.
- **Tested viewports**: 320×568 (iPhone SE worst case), 375×812 (iPhone 13/14), 768 (iPad portrait). Use Playwright at these sizes to verify before claiming a mobile fix done.

## Animation Stack

- **GSAP 3.12 + ScrollTrigger** (CDN) - all entrance/scroll animations
- **Lenis 1.1** (CDN) - smooth scroll, connected to GSAP ticker
- **No SplitText** - paid GSAP plugin, NOT on public CDN. Use clipPath mask reveals.
- **Hash anchors**: `application.js` intercepts `<a href="#...">` clicks for Lenis smooth scroll. Must call `ScrollTrigger.refresh()` before `lenis.scrollTo()` to account for pin spacer heights.
- Turbo lifecycle: kill ScrollTriggers on `turbo:before-render`, reinit Lenis on `turbo:load`
- **Global error logger** (`application.js`): `window.error` + `unhandledrejection` listeners log as `[maison] uncaught error: ...` / `[maison] unhandled promise rejection: ...`. If a page freezes or animation breaks, check console for these tags first.
- **Lenis cleanup is defensive** — `lenis.destroy()`, `gsap.ticker.remove()`, `ScrollTrigger.kill()` are all wrapped in try/catch in `application.js`. The cleanup runs on `turbo:before-render` AND at the start of `turbo:load` (idempotent — kills any leftover state before re-creating).

## Scroll Video (Canvas Frame Sequencer)

121 WebP frames from `scrollvideo.mp4` (desktop) and `scrollvideo-mobile.mp4` (portrait).
Frames ARE committed to the repo (`assets/video-frames/`, ~19MB). Source MP4s are gitignored.

- **`FRAME_START = 0`** in `index.html` (around line 1226) — frame 1 shows the gold ornate cap floating high alone (intentional, the cap-design reveal moment the user explicitly approved). Frames 2-30 show the cap descending while the bottle body fades in. Frames 31+ are the assembled bottle with ingredients. Don't raise this — frame 1 alone is the highlight shot.
- **Mobile video lacks ingredients reveal** — desktop frame 121 shows the ingredient flatlay; mobile frame 121 only shows the bottle. Content limitation, not a code bug.

If frames are missing, re-extract:

```bash
# Desktop
ffmpeg -y -i assets/videos/scrollvideo.mp4 -q:v 2 /tmp/frames-%04d.jpg
for f in /tmp/frames-*.jpg; do cwebp -q 90 -quiet "$f" -o "assets/video-frames/$(basename ${f%.jpg}.webp)"; done

# Mobile
ffmpeg -y -i assets/videos/scrollvideo-mobile.mp4 -q:v 2 /tmp/mframes-%04d.jpg
for f in /tmp/mframes-*.jpg; do cwebp -q 90 -quiet "$f" -o "assets/video-frames/mobile/$(basename ${f%.jpg}.webp)"; done
```

ffmpeg has no WebP encoder on this machine - extract JPEG first, then convert with `cwebp`.

## Testing

**Tests are gitignored** (`server/tests/`, `server/requirements.txt`, `server/pytest.ini`, `server/TESTING.md`) — kept local-only to keep the deploy repo lean. Existing local checkouts have them; fresh clones don't. Re-add via `git rm --cached` if you want them back in the repo.

- Run: `cd server && python3 -m pytest tests/ -v`
- Framework: pytest + pytest-asyncio + httpx
- Tests in `server/tests/` (local only), fixtures in `conftest.py`
- 100% coverage is the goal — write tests for new functions, bug fixes, and conditionals

## Browser Testing

- **Always use Playwright** MCP tools for testing and screenshots. Never use Chrome MCP tools.
- Delegate Playwright work to a subagent via the Agent tool. Never run Playwright directly in the main session.

## Gotchas

- **Dev server**: `cd server && uvicorn app:app --reload --port 3000`. NOT `npx serve` or `python3 -m http.server`.
- **Env vars**: `.env.local` must exist at project root with Supabase credentials. FastAPI loads it via `python-dotenv`.
- **Template source of truth**: `layout.html` renders nav/footer for all public pages. `admin/layout.html` for admin. Login/signup are standalone.
- **Admin auth guard**: `admin/layout.html` has a JS script that checks `maison_admin_auth` in localStorage and redirects to `/admin/login`. Runs before page renders.
- **Product data**: Hardcoded in `app.py` PRODUCTS dict. No database table — products are served directly from code.
- **Server-side price validation**: Orders, cart add, and cart sync all validate product IDs and prices against the `PRODUCTS` dict. Never trust client-provided prices — the server recalculates subtotal/shipping/total from authoritative data.
- **Product image filenames**: `Velvet Waterfall .png` and `Oud Passion .png` have trailing spaces - use URL encoding `%20`.
- **Static files**: Mounted as 4 separate directories (`/static/css`, `/static/js`, `/static/assets`, `/static/admin`) — never exposes project root. Root files (favicon, etc.) served via whitelist route.
- **GSAP SplitText**: Paid plugin. Don't load from CDN - crashes the script.
- **Turbo `turbo:load` listeners need TWO guards**:
  1. **IIFE guard** (per JS load): `(function() { if (window._pageInitBound) return; window._pageInitBound = true; document.addEventListener('turbo:load', function() { ... }); })()` — registers the listener only once, no accumulation.
  2. **Page-presence guard** (per fire): `if (!document.querySelector('.unique-page-element')) return;` as the FIRST line of the listener body. Without this, the listener fires on EVERY Turbo navigation regardless of page → produces dozens of `GSAP target not found` warnings AND can cause real bugs (e.g. `profile.html` was force-redirecting any logged-out user to `/login` on every navigation if they'd ever visited `/profile`). Pattern: landing checks `.hero__video`, story checks `.story-hero`, profile checks `#addressList`, product checks `.product-hero`, cart checks `#cartItems`, checkout checks `#checkoutForm`.

  Animation-heavy pages also need `requestAnimationFrame` wrapping and `ScrollTrigger.refresh()` at the end.
- **`application.js` cache-busting**: Browser aggressively caches this ES module. After editing, bump the `?v=N` query string in `layout.html`.
- **Hash link scrolling**: Lenis blocks native `#hash` scrolling. `application.js` intercepts same-page hash clicks and uses `lenis.scrollTo()` with `ScrollTrigger.refresh()` before scrolling. Cross-page hash links handled in the `turbo:load` handler with a 300ms delay.
- **`cart.js` is global**: Loaded in `layout.html`, not individual templates. `MaisonCart` is available on every page.
- **ScrollTrigger pin vs CSS sticky**: Scroll-video uses `position: relative` - ScrollTrigger handles pinning.
- **Video loop**: Hero `<video>` has NO `loop` attribute - `ended` event advances playlist.
- **Landing page nav override**: `index.html` overrides `{% block nav %}` with its own header inside the hero. Nav changes must be mirrored in THREE places: `layout.html` nav, `index.html` hero nav, AND the `#mobileNav` overlay in `layout.html`.
- **Hero width**: Use `width: 100%` not `100vw` for full-screen sections — `100vw` includes scrollbar width and causes horizontal overflow on mobile.
- **Mobile nav double-init**: `initMobileNav()` runs both immediately and on `turbo:load`. The `dataset.mobileNavInit` guard on each button/link prevents duplicate listeners. Do NOT remove this guard.
- **Scroll-to-top FAB hidden on narrow phones**: `.scroll-top` is `display: none` on `< 480px` via `style.css`. The JS still adds `is-visible` class on scroll, but CSS overrides. Don't try to "fix" the FAB visibility on mobile — it intentionally gets out of the way of long-form content. See the Mobile / Responsive section.
- **Standalone pages + Turbo**: Login, signup, forgot-password, reset-password, admin/login, admin/auth-callback don't extend `layout.html`. Links to them MUST have `data-turbo="false"` — otherwise Turbo SPA-navigates, corrupts GSAP state, and back navigation shows a blank page. **Mobile implication**: standalone pages don't load `style.css`, so any global mobile rules (iOS-zoom prevention, touch-target min-heights, FAB hide) must be DUPLICATED into each standalone page's inline `<style>` block. The 4 customer auth pages currently each inline their own copy of `@media (max-width: 768px) { .auth__input { font-size: 16px !important; } ... }` — keep them in sync when adding new standalone pages.
- **Resend emails**: All auth emails (signup confirm, password reset, admin login) sent via Resend from `noreply@maisonhenius.com`. Routes use `supabase.auth.admin.generate_link()` (service role client) to get verification URLs without Supabase sending email, then `email_service.py` delivers branded HTML via Resend. Exception: `reset-password` creates its own anon client (needs isolated session state for `set_session()`). Module is named `email_service.py` (not `email.py`) to avoid stdlib conflict.
- **Stripe webhook raw body**: The `/api/stripe/webhook` endpoint must read `await request.body()` (raw bytes) for signature verification — parsed JSON breaks the signature check.
- **Stripe StripeObject metadata**: `Webhook.construct_event()` returns `StripeObject` types — `session.metadata` does NOT support `.get()`. Always convert with `.to_dict()` first before accessing keys.
- **Jinja2 `order.items` collision**: In templates, `order.items` on a dict resolves to Python's `dict.items()` method, NOT the `"items"` key. Use `order['items']` bracket notation when the key name collides with dict builtins.
- **Local Stripe testing**: Run `stripe listen --forward-to localhost:3000/api/stripe/webhook` in a separate terminal. The `whsec_...` it outputs goes in `.env.local` as `STRIPE_WEBHOOK_SECRET`.
- **Order status flow**: `/api/checkout/create-session` pre-creates an order with `status="pending"` (abandoned-checkout state — order has full customer info but payment not yet completed). When payment succeeds, `_create_order_from_stripe_session()` calls `_confirm_order()` which transitions `pending → confirmed`, inserts `order_items` for analytics, and clears the server cart. If the user never completes payment, the order stays `pending` forever and the admin sees it in `/admin/orders` filtered by status (so they can call/email the customer to help). Valid statuses: `pending`, `confirmed`, `shipped`, `delivered`, `cancelled`. Changing to shipped/delivered/cancelled auto-sends a branded email to the customer via `email_service.send_order_status_email()`. Pending and confirmed don't trigger emails.
- **`pending` orders are excluded from revenue/total_orders dashboard stats** — `/api/admin/stats` filters by `PAID_STATUSES = {confirmed, shipped, delivered}` for total + revenue, and exposes a separate `pending_orders` count for the abandoned-checkout dashboard tile. Cancelled orders are also excluded from revenue.
- **Don't insert `order_items` during pre-create** — only on the `pending → confirmed` transition (in `_confirm_order`). Otherwise abandoned checkouts would pollute analytics. Same rule for clearing `cart_items`: only when transitioning to confirmed, not on pre-create (the user might come back to retry).
- **Cart sync is server-authoritative for logged-in users** — `cart.js loadFromServer()` always overwrites localStorage with the server cart (empty included). Don't add merge logic here — that's what caused the "stale cart after checkout" bug. The merge logic for guest→login transition lives in `sync()`, called explicitly from `login.html`.
- **`loadFromServer()` skips on `/checkout/success`** — guard at the top of the function. Removing it re-introduces a race where the in-flight server fetch repopulates localStorage after the page script clears it.
- **`cart.js` evicts stale tokens on 401**: `loadFromServer()` checks for `r.status === 401` and removes `maison_auth` from localStorage. Without this, an expired JWT keeps re-firing /api/cart on every Turbo navigation. Don't replace with a retry loop — the token is dead, the user needs to re-login.
- **Postal code conditionally required in checkout**: `checkout.html` defines `REQUIRES_POSTAL = { US: 1, GB: 1, FR: 1, DE: 1 }` — only those countries require postal_code. UAE, KSA, Gulf countries are optional. When adding a new country to the `<select>`, also decide if it belongs in REQUIRES_POSTAL. The `syncPostalRequired()` listener toggles the input's `required` attribute + the `(optional)` label hint based on the current selection.
- **First checkout auto-saves to profile**: `/api/checkout/create-session` checks if the user has zero saved addresses; if so, the address they typed in checkout is auto-inserted into the `addresses` table with `is_default=true`. So the second time they checkout, the address is already saved + can be reused. Wrapped in try/except so a save failure doesn't block payment. Address shows in `/profile` immediately on next visit. Trigger condition: `address.line1 AND address.city` must be present (ignores partial submissions).
- **`/checkout/success` is self-healing** — the route uses Stripe API to verify the session, then calls `_create_order_from_stripe_session()` (the same helper the webhook uses) to create the order + clear the server cart. Idempotent via existing-order check. If you change the webhook order-creation logic, change the helper, not the webhook handler — both code paths flow through it.
- **Don't change middleware order in `app.py`** — `CacheControlMiddleware` must be added BEFORE `GZipMiddleware`. Starlette runs `add_middleware()` calls in reverse order on responses, so the last one added is the outermost. GZip needs to wrap CacheControl so `Vary: Accept-Encoding` lands after the cache headers are set.
- **Railway's Fastly is a passthrough, not a cache** — every response shows `x-cache: MISS` even with valid `Cache-Control` headers. Don't try to "fix" this with surrogate headers; it's a platform-level limitation. The cache headers are still useful for **browser** caching. For real shared edge caching across users, the move is Cloudflare in front of Railway when the custom domain is set up.
- **Always check image dimensions before encoding** — `cwebp` doesn't auto-resize. If you forget `-resize WIDTH 0`, you'll ship a 4K image that displays at 600px and wastes ~1 MB per file (we did this with cards originally). Run `webpinfo file.webp` to verify dimensions after encoding.
- **HTML `width`/`height` on images with CSS `aspect-ratio`**: adding `width="X" height="Y"` to an `<img>` is great for CLS, BUT if the CSS rule relies on `aspect-ratio` without an explicit `height`, the HTML attributes act as presentational hints (`height: Ypx`) that override `aspect-ratio` → the image renders as a tall rectangle instead of the intended square. Fix: add `height: auto` to the CSS rule. Example: `.product-comp__note-img { width: 100%; height: auto; aspect-ratio: 1; ... }`. Already bit us once on the ingredient grid on product detail pages.
- **Scroll-video preloader is throttled on purpose** — `preload()` in `index.html` uses a concurrency pool of 6 (matches browser per-origin HTTP/1.1 cap) and draws `FRAME_START` the instant it arrives, rather than waiting for all 121 frames. Do NOT "simplify" this back to a tight `for (i=0; i<TOTAL; i++) new Image()` loop — that was the original P0 perf bug (blank canvas for 15+ seconds on slow networks). The `ScrollTrigger.create()` call is still deferred until all frames load, so the scroll animation contract is unchanged.
- **`cart.js` localStorage items include `serverId`** (not just product `id`). When a logged-in user adds/updates/removes items, the cached `serverId` lets mutations go through in 1 round-trip instead of 2 (old pattern was GET-then-DELETE/PATCH). Legacy items without `serverId` still work via a one-off GET fallback in `_findServerItemId()`. Don't strip the field thinking it's dead code.

## Deployment (Railway)

- **Live URL**: https://web-production-cc74a0.up.railway.app
- **GitHub repo**: https://github.com/Maisonhenius/maison (public, lean ~46MB)
- **Railway project**: `maison-henius` (id: `f45a16f9-e777-4cce-abd1-dcd08c2ccb56`), service `web`, environment `b99a4d18-a9fc-4742-b874-c0b4d38e5ade`
- **Builder**: Dockerfile (clones from GitHub on Railway servers — bypasses upload size limits)
- **Deploy directory**: `/tmp/claude/maison-docker-deploy/` contains only `Dockerfile` + `Procfile` (8KB upload)

### Redeploy

1. Push changes to `https://github.com/Maisonhenius/maison` `main` branch
2. Bump the cache-bust string in the Dockerfile (e.g. `v6` → `v7`) — Docker caches the `git clone` layer, the version string forces a fresh clone
3. Run: `cd /tmp/claude/maison-docker-deploy && railway up --project f45a16f9-e777-4cce-abd1-dcd08c2ccb56 --environment b99a4d18-a9fc-4742-b874-c0b4d38e5ade --service web --ci -m "<message>"`

### Still needed before custom domain

- **Stripe webhook secret** (currently `whsec_placeholder`) — create webhook in Stripe Dashboard pointing to `/api/stripe/webhook`, paste signing secret into Railway env
- **Custom domain** `maisonhenius.com` via `railway domain --custom`
- Replace `https://maisonhenius.com/` placeholder in `index.html` `og:image`
- Add `sitemap.xml`, proper `og:image` (1200x630 brand image)

## Image & Video Assets (WebP / H.264 only)

All product/landscape images in the deployed repo are WebP. Originals (PNG/JPG) stay local and are gitignored.

- **Tracked in git**: `assets/pictures/Collection & Fragrances/*.webp`, `assets/pictures/Jordan Landscape/*.webp`, `assets/pictures/ingredients/*.webp`, `assets/video-frames/**/*.webp`, `assets/videos/web/*.mp4`
- **Gitignored** (originals only): `*.png`, `*.jpg`, `*.jpeg` in those folders, `assets/videos/*.mp4` (raw source videos), `assets/videos/web-original-backup/` (pre-encoding hero videos, kept locally for rollback)
- **Templates reference `.webp`** — never `.png`. PRODUCTS dict in `app.py` uses `.webp` for `card_image` and `bottle_image`.

### Image size targets (don't ship oversized assets)

| Asset type | Max width | cwebp quality | Target file size | Notes |
|---|---|---|---|---|
| Card images (`card-*.webp`) | **1200px** | `-q 78` | 200-300 KB each | Display ~600px on screen, retina-ready |
| Bottle images (`Out of Control.webp` etc.) | 832px (current) | `-q 80` | ~50 KB each | Already optimal |
| Bottle reflection (story page) | **1600px** | `-q 80` | ~32 KB | Was 5504px originally |
| Ingredient images (`ingredients/*.webp`) | **800px** | `-q 80` | ~150 KB each | Square aspect for note grid |
| Jordan landscapes | ~1300px (current) | `-q 80` | ~150-200 KB | Already optimal |
| Scroll video frames | 1928×1072 (current) | `-q 90` | ~50-160 KB per frame | Don't shrink — canvas needs detail |

### Recipes

```bash
# Card image (4K source → 1200px web)
cwebp -q 78 -resize 1200 0 input.png -o output.webp

# Ingredient (any source → 800px square)
cwebp -q 80 -resize 800 0 input.png -o output.webp

# Hero video (1080p source → 720p H.264 ~1 Mbps, no audio, streamable)
ffmpeg -y -i input.mp4 -c:v libx264 -preset slow -crf 26 -vf "scale=1280:-2" -an -movflags +faststart output.mp4
```

**Lesson learned:** card images were originally encoded at 4096×4096 (full 4K) because cwebp doesn't auto-resize. This cost ~7 MB on every landing page paint. Always check dimensions with `webpinfo file.webp` before deploying.

## Nano Banana asset workflow

When editing existing brand images via the `nano-banana` skill:

1. **Pass the existing image as input** — never generate from scratch when editing. The skill needs the original to preserve composition.
2. **Save with a distinct filename** (e.g. `patchouli-green.webp`, `card-parisian-v2.webp`). Never overwrite the original.
3. **Verify dimensions + format** — Nano Banana sometimes returns JPEG bytes with a `.webp` extension. Run `webpinfo` to check, re-encode with `cwebp -q 78 -resize WIDTH 0` if wrong.
4. **Promote to canonical name** by renaming after approval: `mv original.webp original-backup.webp && mv new.webp original.webp`. The `-backup` suffix is descriptive (e.g. `coffee-beans.webp`, `patchouli-dried.webp`, `card-parisian-original.webp`). Backups stay in git as fallback.
5. **Path renaming preserves Jinja captions**: templates like `products/detail.html` build the ingredient name from the filename via `{{ img | replace('-', ' ') | title }}`. So `patchouli-green.webp` would render as "Patchouli Green" in the UI — promote to canonical `patchouli.webp` to keep "Patchouli" as the display name.

Current AI-edited assets (with backups available): `patchouli.webp` (backup: `patchouli-dried.webp`), `coffee.webp` (backup: `coffee-beans.webp`), `card-parisian.webp` (backup: `card-parisian-original.webp`), `card-out-of-control.webp` (backup: `card-out-of-control-original.webp`), `Maison Henius - universe.webp` (sibling of original `Maison Henius.webp`).

## Performance

Three layers in `server/app.py` near the top of the file:

1. **`mimetypes.add_type("image/webp", ".webp")`** — runs at import time, BEFORE any `StaticFiles` mount. Fixes the default Linux mimetypes registry that was serving WebP as `text/plain`. Required for browsers and CDNs to recognize WebP correctly.
2. **`CacheControlMiddleware`** (custom class, in app.py) — sets `Cache-Control` on static asset responses based on path:
   - `/static/css/*`, `/static/js/*`, `/static/admin/*` → `public, max-age=31536000, immutable` (cache-busted via `?v=N` in template references)
   - `/static/assets/*` → `public, max-age=2592000` (30 days; product images, hero videos, scroll frames, music)
   - `/static/*` (root favicons, robots.txt) → `public, max-age=86400` (1 day)
   - **HTML pages and API responses get NO cache header** so they stay fresh
3. **`GZipMiddleware(minimum_size=500)`** — compresses HTML/CSS/JS/JSON ~70-80%. Skips already-compressed binary content.

Middleware order matters — see the gotcha in the Gotchas section.

### Backend request model

- **All Supabase/Stripe/Resend calls are offloaded to worker threads** via the `_db()` / `_to_thread()` helpers (see the "Async DB Helpers" section). This keeps the asyncio event loop free to serve concurrent requests. Verified empirically: 5 parallel `/api/profile` requests finish in ~800ms vs ~1900ms sequential (2.4×).
- **Independent reads are parallelized with `asyncio.gather`** in `/api/profile` (profile + addresses + orders) and `/api/admin/stats` (orders + messages).
- **Admin list endpoints are capped at 500 rows** via `.limit(500)` so the admin dashboard can't get crushed as tables grow.

### Railway / Fastly caching limitation

Railway's edge proxy is Fastly, but it acts as a **passthrough**, not a cache. Even with proper `Cache-Control` headers, every response shows `x-cache: MISS` and hits the origin in `europe-west4`. Verified by sending 5 sequential requests through the same Fastly cache server — all 5 were MISS. **Don't waste time trying to "fix" the edge cache via headers — it's a platform-level limitation.**

The wins from the cache headers come from **browser caching**, not edge caching:
- A returning visitor or within-session navigation hits the local browser cache (1 year for CSS/JS, 30 days for assets) → instant
- TTFB on first hit is still ~600ms (network + origin), but the asset payload is gzipped → ~70% smaller transfer

For real edge caching across multiple users, the move is **Cloudflare in front of Railway** when the custom domain is set up — Cloudflare will respect our cache headers and serve hot assets from PoPs in 200+ cities.

## Stripe (current state)

- **Test mode** is active in production (test keys in Railway env)
- **Webhook not yet configured on production** — `STRIPE_WEBHOOK_SECRET=whsec_placeholder`. **The system still works** because `/checkout/success` is self-healing (verifies the Stripe session via API and calls `_create_order_from_stripe_session()` as a fallback). Configuring the webhook is still recommended for instant order creation (no dependency on the user landing on the success page) and for handling other Stripe events later.
- **Local testing**: `stripe listen --forward-to localhost:3000/api/stripe/webhook`. Local secret is in `.env.local`

## Future
- **Turbo Frames**: Cart badge, admin stats as independent frames
- **Turbo Streams**: Real-time admin updates via SSE
- **Stimulus Controllers**: Migrate inline scripts to proper controllers
- **Re-enable CI** — `.github/workflows/test.yml` was removed because it ran pytest from `server/`, but `server/tests/` and `server/requirements.txt` are gitignored. Re-adding requires either un-ignoring those files or writing a new workflow that hits the live URL after Railway deploys
