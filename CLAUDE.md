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
| `/api/admin/orders` | GET | Admin | List all orders |
| `/api/admin/orders/{id}` | PATCH | Admin | Update order status + send customer email (shipped/delivered/cancelled) |
| `/api/admin/messages` | GET | Admin | List all contact messages |
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
- **addresses**: id (uuid), user_id, full_name, line1, line2, city, state, postal_code, country, is_default, created_at
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
- Legal entity: "Marisal Goods wholesalers -FZE" (not "Maison Henius") in footer copyright

## Animation Stack

- **GSAP 3.12 + ScrollTrigger** (CDN) - all entrance/scroll animations
- **Lenis 1.1** (CDN) - smooth scroll, connected to GSAP ticker
- **No SplitText** - paid GSAP plugin, NOT on public CDN. Use clipPath mask reveals.
- **Hash anchors**: `application.js` intercepts `<a href="#...">` clicks for Lenis smooth scroll. Must call `ScrollTrigger.refresh()` before `lenis.scrollTo()` to account for pin spacer heights.
- Turbo lifecycle: kill ScrollTriggers on `turbo:before-render`, reinit Lenis on `turbo:load`

## Scroll Video (Canvas Frame Sequencer)

121 WebP frames from `scrollvideo.mp4` (desktop) and `scrollvideo-mobile.mp4` (portrait).
Frames ARE committed to the repo (`assets/video-frames/`, ~19MB). Source MP4s are gitignored.

- **`FRAME_START = 30`** in `index.html` (around line 1177) — frames 0-29 show a detached bottle cap floating above a capless bottle body, which looks like a rendering bug. Animation starts at frame 30 where the bottle is fully assembled. Don't lower this without re-checking the source frames.
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
- **Turbo `turbo:load` listeners**: Inline `turbo:load` listeners use the guard IIFE pattern — wrap in `(function() { if (window._pageInitBound) return; window._pageInitBound = true; document.addEventListener('turbo:load', function() { ... }); })()`. This registers the listener only once (no accumulation) while allowing it to fire on back/forward navigation (unlike `{ once: true }` which breaks snapshot restoration). Animation-heavy pages also need `requestAnimationFrame` wrapping and `ScrollTrigger.refresh()` at the end.
- **`application.js` cache-busting**: Browser aggressively caches this ES module. After editing, bump the `?v=N` query string in `layout.html`.
- **Hash link scrolling**: Lenis blocks native `#hash` scrolling. `application.js` intercepts same-page hash clicks and uses `lenis.scrollTo()` with `ScrollTrigger.refresh()` before scrolling. Cross-page hash links handled in the `turbo:load` handler with a 300ms delay.
- **`cart.js` is global**: Loaded in `layout.html`, not individual templates. `MaisonCart` is available on every page.
- **ScrollTrigger pin vs CSS sticky**: Scroll-video uses `position: relative` - ScrollTrigger handles pinning.
- **Video loop**: Hero `<video>` has NO `loop` attribute - `ended` event advances playlist.
- **Landing page nav override**: `index.html` overrides `{% block nav %}` with its own header inside the hero. Nav changes must be mirrored in THREE places: `layout.html` nav, `index.html` hero nav, AND the `#mobileNav` overlay in `layout.html`.
- **Hero width**: Use `width: 100%` not `100vw` for full-screen sections — `100vw` includes scrollbar width and causes horizontal overflow on mobile.
- **Mobile nav double-init**: `initMobileNav()` runs both immediately and on `turbo:load`. The `dataset.mobileNavInit` guard on each button/link prevents duplicate listeners. Do NOT remove this guard.
- **Standalone pages + Turbo**: Login, signup, forgot-password, reset-password, admin/login, admin/auth-callback don't extend `layout.html`. Links to them MUST have `data-turbo="false"` — otherwise Turbo SPA-navigates, corrupts GSAP state, and back navigation shows a blank page.
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
- **`/checkout/success` is self-healing** — the route uses Stripe API to verify the session, then calls `_create_order_from_stripe_session()` (the same helper the webhook uses) to create the order + clear the server cart. Idempotent via existing-order check. If you change the webhook order-creation logic, change the helper, not the webhook handler — both code paths flow through it.

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

## Image Assets (WebP only)

All product/landscape images in the deployed repo are WebP. Originals stay local (gitignored).

- **Convert new images**: `cwebp -q 82 input.png -o input.webp` (add `-resize 800 0` for ingredient photos)
- **Tracked in git**: `assets/pictures/Collection & Fragrances/*.webp`, `assets/pictures/Jordan Landscape/*.webp`, `assets/pictures/ingredients/*.webp`, `assets/video-frames/**/*.webp`
- **Gitignored** (originals only): `*.png`, `*.jpg`, `*.jpeg` in those folders
- **Templates reference `.webp`** — never `.png` for product images. PRODUCTS dict in `app.py` uses `.webp` for `card_image` and `bottle_image`

## Stripe (current state)

- **Test mode** is active in production (test keys in Railway env)
- **Webhook not yet configured on production** — `STRIPE_WEBHOOK_SECRET=whsec_placeholder`. **The system still works** because `/checkout/success` is self-healing (verifies the Stripe session via API and calls `_create_order_from_stripe_session()` as a fallback). Configuring the webhook is still recommended for instant order creation (no dependency on the user landing on the success page) and for handling other Stripe events later.
- **Local testing**: `stripe listen --forward-to localhost:3000/api/stripe/webhook`. Local secret is in `.env.local`

## Future
- **Turbo Frames**: Cart badge, admin stats as independent frames
- **Turbo Streams**: Real-time admin updates via SSE
- **Stimulus Controllers**: Migrate inline scripts to proper controllers
- **Re-enable CI** — `.github/workflows/test.yml` was removed because it ran pytest from `server/`, but `server/tests/` and `server/requirements.txt` are gitignored. Re-adding requires either un-ignoring those files or writing a new workflow that hits the live URL after Railway deploys
