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
    story.html            <- Our Story / Universe page (centered text + image sections)
    terms.html            <- Terms & Conditions (extends layout, `.legal-*` CSS)
    privacy.html          <- Privacy Policy (extends layout, `.legal-*` CSS)
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
  music/music.mp3         <- (unused) Old background audio loop. Hero video now has its own audio baked in.
  videos/web/             <- Web-optimized videos: brand-film.{mp4,webm} (hero) + scroll-cinematic.mp4 (scroll cinematic, 844KB H.264 Main yuv420p faststart, no audio)
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
| `/terms` | GET | None | Terms & Conditions page |
| `/privacy` | GET | None | Privacy Policy page |
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
- **Global `img { border-radius: 12px }` in `style.css`**: Applies to ALL images. Full-bleed sections (`.product-mood__img`, `.story-hero__img`) need explicit `border-radius: 0` to override. Check this when adding any new edge-to-edge image section.
- **Hamburger nav < 768px**: `.nav__hamburger` shown, `.nav__left` hidden. Nav switches from flex to **CSS grid** (`grid-template-columns: 1fr auto 1fr`) to center the logo regardless of left/right content width. The hamburger is `justify-self: start`, logo is `justify-self: center`, right icons are `justify-self: end`. Pattern lives in `style.css` `@media (max-width: 768px)`.
- **Scroll-to-top FAB shows on all viewports** (44×44px touch target). The old `< 480px` hide rule was removed. Watch for overlap with `/story` pillar text at narrow widths — if it bites again, add a selective per-page hide instead of global.
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
- **Scroll cinematic uses `<video>` + `currentTime` scrub (NOT canvas + frame sequencer).** Hardware H.264 decoder owns the frame buffer (~30 MB peak, browser-managed, reclaimable under memory pressure). The prior canvas approach held 121 × 8.3 MB ImageBitmaps (~1 GB) and crashed iOS Safari tabs ("A problem repeatedly occurred" / "Can't open this page" on Chrome iOS, which is also WebKit). Cover-fit is now CSS `object-fit: cover`; portrait `MOBILE_SCALE` is now CSS `transform: scale(0.72)` under `@media (orientation: portrait)`. Sticky + section backgrounds are pure `#000` so the transform-induced bands are invisible. **Don't revert to canvas + frames** — see Scroll Cinematic section below.

## Scroll Cinematic (`<video>` element + `currentTime` scrub)

`assets/videos/web/scroll-cinematic.mp4` — a ~5s Seedance-generated cap-onto-bottle reveal on a pure `#000` void background. 1920×1080 H.264 Main profile / yuv420p / faststart / no audio / 844 KB. Re-encoded from the gitignored source `assets/videos/scroll-video-3.mp4`. The MP4 is committed; the source MP4 is gitignored.

**Why `<video>` + `currentTime` and NOT canvas + frames:** the prior canvas implementation preloaded all 121 WebP frames as ImageBitmaps in JS heap (1920×1080 × 4 bytes × 121 = ~1 GB of decoded RGBA). iOS Safari per-tab memory budget is ~120-400 MB depending on device, so EVERY iPhone OOM-killed the tab and showed "A problem repeatedly occurred" (or Chrome iOS's "Can't open this page" — Chrome iOS is WebKit too). The video element pushes decoding into the browser's hardware video pipeline, capping memory at ~30 MB regardless of length. Same source video, same 1920×1080 pixels, same 5-second timeline, same scrub feel — bulletproof on every device.

- **HTML**: `<video class="scroll-video__media" muted playsinline webkit-playsinline preload="auto" disableRemotePlayback aria-hidden="true">` inside `.scroll-video__sticky`. `muted` + `playsinline` is the iOS-blessed combination for inline rendering without autoplay; we never call `play()` because `currentTime` updates render frames on a paused video just fine. `disableRemotePlayback` removes the "Stream to AirPlay" UI from Safari.
- **Cover-fit + MOBILE_SCALE in CSS**: `object-fit: cover` does the cover-fit math the canvas implementation did manually. `@media (orientation: portrait) { transform: scale(0.72) }` does the MOBILE_SCALE multiplier — same 0.72 value, same goal (keep the cap + bottle subject visible on tall phones where straight cover-fit clips the sides). Pure `#000` sticky bg hides the resulting bands.
- **JS scrub** (~30 lines, in `index.html`): `ScrollTrigger.create({ ..., onUpdate: function(self) { targetTime = self.progress * video.duration; requestAnimationFrame(applyScrub); } })`. The `requestAnimationFrame` wrapper coalesces rapid scroll deltas — without it, mobile touch scroll fires `onUpdate` faster than the video can seek. `applyScrub` no-ops when `Math.abs(video.currentTime - targetTime) < 0.001` to avoid redundant seeks.
- **First-frame paint**: `video.currentTime = 0.001` is set on `loadeddata` to force iOS Safari to decode and render the first frame BEFORE any scroll happens. Without this nudge, the `<video>` element renders transparent until the first user-driven `currentTime` change. The 0.001s offset is invisible (the cap-alone hero frame is at t=0).
- **Scroll distance is tapered** (CSS): `400vh` desktop, `300vh` under 768px, `250vh` under 480px (3-screen-tall scrubs feel interminable on a phone). Unchanged from the canvas era.
- **Section + sticky backgrounds are pure `#000`** (not brand `#0a0a08`) so the `MOBILE_SCALE` letterbox bars are visually invisible. Same as before.
- **No `prefers-reduced-motion` fallback.** The scroll scrub is brand-critical and runs for all viewers regardless of OS "Reduce motion" setting. WCAG 2.3.3 AAA non-compliance is a conscious choice.
- **No poster image, no preloaded image.** Per user direction "always a video, never an image": the section's `#000` background covers the brief moment before the video metadata loads (~50-200 ms on first paint). When the user scrolls into view, the video element is already showing frame 0. The scroll cinematic is BELOW the fold, so any metadata-load delay is invisible in normal usage.
- **iOS Low Power Mode**: `currentTime` updates render frames even when iOS LPM blocks autoplay (LPM blocks `play()` specifically, not seek-driven rendering). Verified WebKit behavior. Worst case if LPM somehow does block: section shows pure `#000`, user scrolls past, no crash.

If you need to re-encode the cinematic from the source MP4:

```bash
ffmpeg -y -i assets/videos/scroll-video-3.mp4 \
  -c:v libx264 -preset slow -crf 22 \
  -profile:v main -level 4.0 \
  -pix_fmt yuv420p \
  -an \
  -movflags +faststart \
  assets/videos/web/scroll-cinematic.mp4
```

**Why these flags**: H.264 Main profile + Level 4.0 + yuv420p = universal Safari/iOS compatibility (avoids High 10 / 422 chroma profiles that break iOS playback). `-an` strips audio (the cinematic is silent). `+faststart` puts the moov atom at the start of the file so the browser can begin decoding before the full file arrives — critical for HTTP range-request streaming and progressive playback on slow networks. CRF 22 is visually transparent quality.

## Testing

**Tests are gitignored** (`server/tests/`, `server/requirements.txt`, `server/pytest.ini`, `server/TESTING.md`) — kept local-only to keep the deploy repo lean. Existing local checkouts have them; fresh clones don't. Re-add via `git rm --cached` if you want them back in the repo.

- Run: `cd server && python3 -m pytest tests/ -v`
- Framework: pytest + pytest-asyncio + httpx
- Tests in `server/tests/` (local only), fixtures in `conftest.py`
- 100% coverage is the goal — write tests for new functions, bug fixes, and conditionals

## Browser Testing

- **Always use Playwright** MCP tools for automated testing and screenshots. Never use Chrome MCP tools.
- Delegate Playwright work to a subagent via the Agent tool. Never run Playwright directly in the main session.
- **For quick visual checks**: Don't spawn Playwright agents. Instead, ensure the local dev server is running and tell the user which URL to check in their own browser. Only use Playwright for comprehensive automated testing or when explicitly requested.

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
- **Hero video is SILENT (no audio track) + separate `<audio>` element for sound toggle**: `assets/videos/web/brand-film-silent.{mp4,webm}` are the autoplaying hero video (audio stripped via `ffmpeg -c:v copy -an`); `brand-film-audio.m4a` is the standalone audio (extracted via `ffmpeg -vn -c:a copy`). **Why split**: macOS Safari blocks autoplay of any video that contains an audio track, even when `muted` is set, on low-engagement sites — the play-button overlay stays. Stripping the audio track entirely makes autoplay structurally impossible to block (silent videos always autoplay regardless of policy). Source order is **MP4 first, WebM second** so Safari grabs H.264 directly without trying VP9+Opus (which it stalls on). JS also calls `heroVideo.play().catch()` on `loadeddata` to bypass Safari's autoplay-attribute timing — without it Safari waits for `canplaythrough` instead of `canplay`, adding a multi-second delay on a 9 MB hero film. The sound toggle plays/pauses `<audio id="heroAudio" loop>`; on first activation it sets `heroAudio.currentTime = heroVideo.currentTime % heroAudio.duration` so audio starts at the visual moment the user is currently seeing. Both loop independently afterward (~62s each); minor drift is imperceptible for ambient brand music. Original `web/brand-film.{mp4,webm}` (with audio) were deleted from git after the split — only the silent + audio pair are tracked. Source file (`assets/videos/Brand film.mp4`, 124 MB) is gitignored.
- **`.m4a` MIME type is registered in `app.py`**: `mimetypes.add_type("audio/mp4", ".m4a")` runs at import time. Without it, Python's default registry on Linux emits `audio/mp4a-latm` (non-standard low-overhead-AAC subtype) which some browsers/CDNs reject. Required because the hero `<audio>` source loads `brand-film-audio.m4a`. Sits next to the existing `mimetypes.add_type("image/webp", ".webp")` registration.
- **iOS Safari `100dvh` pattern for the toolbar collapse bug**: every `100vh` in the codebase is paired with a `100dvh` override on the next line. iOS Safari shows the URL/toolbar on first paint then collapses it; `100vh` is the LARGE viewport (toolbar collapsed) so content gets cut off below the visible toolbar. `100dvh` is the DYNAMIC viewport that adjusts in real-time. Pattern: `height: 100vh; height: 100dvh;` — older browsers ignore the `dvh` line and use `vh`, modern browsers (Safari 15.4+ / Chrome 108+) use `dvh`. Applied in `index.html` (.hero, .scroll-video__sticky), `story.html` (.story-hero), `cart.html`, `checkout.html`, `checkout-success.html`, `login.html`, `signup.html`, `forgot-password.html`, `reset-password.html`, `admin/login.html`, `admin/auth-callback.html`, `admin/admin.css` (.admin, .admin__sidebar, .admin__main). When adding a new full-height container, ALWAYS use this pattern.
- **Hash link scrolling**: Lenis blocks native `#hash` scrolling. `application.js` intercepts same-page hash clicks and uses `lenis.scrollTo()` with `ScrollTrigger.refresh()` before scrolling. Cross-page hash links handled in the `turbo:load` handler with a 300ms delay.
- **`cart.js` is global**: Loaded in `layout.html`, not individual templates. `MaisonCart` is available on every page.
- **ScrollTrigger pin vs CSS sticky**: Scroll-video uses `position: relative` - ScrollTrigger handles pinning.
- **Video encoding — long-form (brand film, 60s+)**: VP9 single-pass CRF doesn't beat H.264 CRF 26 for file size (CRF 32 came out 11 MB vs H.264's 8.83 MB). Use **VP9 2-pass at target bitrate** (~800 kbps for 720p) to match H.264 quality at ~30% smaller. H.264 recipe for long-form: `-preset veryslow -tune film -crf 26`. Verify with `ffprobe -v error -show_entries stream=codec_type,codec_name,bit_rate -of default=noprint_wrappers=1 file.{mp4,webm}`.
- **Landing page nav override**: `index.html` overrides `{% block nav %}` with its own header inside the hero. Nav changes must be mirrored in THREE places: `layout.html` nav, `index.html` hero nav, AND the `#mobileNav` overlay in `layout.html`.
- **Hero width**: Use `width: 100%` not `100vw` for full-screen sections — `100vw` includes scrollbar width and causes horizontal overflow on mobile.
- **Mobile nav double-init**: `initMobileNav()` runs both immediately and on `turbo:load`. The `dataset.mobileNavInit` guard on each button/link prevents duplicate listeners. Do NOT remove this guard.
- **Standalone pages + Turbo**: Login, signup, forgot-password, reset-password, admin/login, admin/auth-callback don't extend `layout.html`. Links to them MUST have `data-turbo="false"` — otherwise Turbo SPA-navigates, corrupts GSAP state, and back navigation shows a blank page. **Mobile implication**: standalone pages don't load `style.css`, so any global mobile rules (iOS-zoom prevention, touch-target min-heights, FAB hide) must be DUPLICATED into each standalone page's inline `<style>` block. The 4 customer auth pages currently each inline their own copy of `@media (max-width: 768px) { .auth__input { font-size: 16px !important; } ... }` — keep them in sync when adding new standalone pages.
- **Resend emails**: All auth emails (signup confirm, password reset, admin login) sent via Resend from `noreply@maisonhenius.com`. Routes use `supabase.auth.admin.generate_link()` (service role client) to get verification URLs without Supabase sending email, then `email_service.py` delivers branded HTML via Resend. Exception: `reset-password` creates its own anon client (needs isolated session state for `set_session()`). Module is named `email_service.py` (not `email.py`) to avoid stdlib conflict.
- **Stripe webhook raw body**: The `/api/stripe/webhook` endpoint must read `await request.body()` (raw bytes) for signature verification — parsed JSON breaks the signature check.
- **Stripe StripeObject metadata**: `Webhook.construct_event()` returns `StripeObject` types — `session.metadata` does NOT support `.get()`. Always convert with `.to_dict()` first before accessing keys.
- **Stripe metadata value limit**: Each metadata value on a Stripe Checkout Session is capped at **500 characters**. `items_json` in the checkout metadata stores only `id` and `quantity` per item (NOT name/family/price — those are re-validated from `PRODUCTS` dict in the fallback path). With 5 products at full verbosity the old format hit 522 chars and broke checkout.
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
- **`CacheControlMiddleware` MUST skip error responses (4xx/5xx)** — the middleware sets `Cache-Control: public, max-age=2592000` on static assets by PATH, but without a status-code guard it will happily slap that header on a 404 too, poisoning the client cache for 30 days. If a visitor hits a missing `/static/assets/...` URL once, their browser serves the cached 404 until the header expires — even after you add the asset. There's a guard at `app.py:100-103` (`if not 200 <= status < 300: return response`). Don't remove it. 2xx responses (including 206 partial-content for video range requests) still get cached — the guard uses a range check, not a strict `== 200`.
- **Always check image dimensions before encoding** — `cwebp` doesn't auto-resize. If you forget `-resize WIDTH 0`, you'll ship a 4K image that displays at 600px and wastes ~1 MB per file (we did this with cards originally). Run `webpinfo file.webp` to verify dimensions after encoding.
- **Square images — NEVER use `aspect-ratio`**: CSS `aspect-ratio: 1` breaks in flex containers, inline-block, and when HTML width/height attributes are present. Use explicit `width` + `height` (same value) on the container + `overflow: hidden`, then `width: 100%; height: 100%; object-fit: cover` on the `<img>`. Remove HTML `width`/`height` attributes from the `<img>` tag when using this pattern. The `aspect-ratio` approach has failed repeatedly — don't retry it.
- **Square containers in CSS grid — use padding-bottom trick**: `aspect-ratio: 1` on a grid child inflates the track and causes overflow. Instead: set `padding-bottom: 100%; position: relative; overflow: hidden` on the wrapper, then `position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover` on the `<img>`. This is what `.product-explore__card-img` uses.
- **Scroll cinematic uses native `<video>` + `currentTime` scrub, not canvas + ImageBitmap.** See the Scroll Cinematic section above for the architecture. The previous canvas-based implementation (121 WebP frames preloaded as ImageBitmaps) crashed iOS Safari tabs with OOM. **Don't revert.** If scroll smoothness regresses, debug the `requestAnimationFrame` coalescing in the `applyScrub` function — don't swap back to frame extraction.
- **Cart badge offset on mobile**: `.nav__cart` gets `padding: 13px` for touch targets on mobile, which shifts the absolutely-positioned `.cart-badge` away from the icon. The mobile breakpoint in `style.css` overrides badge position to `top: 2px; right: 0px` to compensate. If you change the padding, recalculate the badge offset.
- **GSAP `fromTo` + lazy images flicker**: Don't use `gsap.fromTo(el, {opacity:0}, {opacity:1})` on images with `loading="lazy"` or `decoding="async"`. The browser renders the image visible, GSAP resets to opacity:0 (disappears), then animates back (reappears) — visible flicker. Fix: set initial hidden state in CSS (`opacity: 0`), remove `loading="lazy"`, and use `gsap.to()` instead of `fromTo`. Applied on `.product-bottle__img`.
- **Pseudo-element overflow on mobile**: `.story-craft__image::before` has `inset: -10% -5%` for a gold halo glow. On mobile, the 5% horizontal bleed extends beyond the viewport and causes horizontal scroll. `.story-craft` gets `overflow: hidden` at `< 768px` to contain it. Check for similar pseudo-element bleed on any section with decorative `::before`/`::after` that uses negative inset.
- **Product explore cards**: `products/detail.html` "Explore More" grid uses a `.product-explore__card-img` wrapper div around the `<img>`, with the product name as a separate `<span>` below (not overlaid). Don't add gradient overlays on the image — the name is intentionally outside.
- **Three product image sections are INDEPENDENT — don't conflate them**: (1) Landing page collection cards use `card_image` (old squares), (2) Product Explore More uses `card_image` (same old squares), (3) Product Mood section uses `mood_image` (new landscape). Changing one section's images does NOT mean changing the others. Always ask which section before swapping images.
- **Ingredient changes touch THREE assets**: When replacing an ingredient (e.g. star anise → cool spices), update: (1) the ingredient image in `assets/pictures/ingredients/`, (2) the bottle hero image in `Collection & Fragrances/bottle-{slug}.webp`, and (3) the card image `card-{slug}.webp`. Missing any one leaves the old ingredient visible on the product page.
- **Shared ingredient images need copies, not renames**: `rose.webp`, `coffee.webp` etc. are used across multiple products. To change the display name for ONE product (e.g. "Rose" → "Moldavian Rose" on Oud Passion only), copy `rose.webp` → `moldavian-rose.webp` and update only that product's `images` array. The template renders display names from filenames via `{{ img | replace('-', ' ') | title }}`.
- **Hard refresh needed after image swaps**: Static assets have 30-day `Cache-Control`. After replacing an image file (same filename, new content), users must Cmd+Shift+R or use incognito. Warn the user proactively when swapping images in-place.
- **Recovering overwritten images from git**: `git show COMMIT:'assets/pictures/Collection & Fragrances/filename.webp' > new-filename.webp`. Use `git log --oneline --follow -- 'path/to/file'` to find the commit before the overwrite. Save with a DISTINCT filename — never overwrite the current file before confirming with the user.
- **`cart.js` localStorage items include `serverId`** (not just product `id`). When a logged-in user adds/updates/removes items, the cached `serverId` lets mutations go through in 1 round-trip instead of 2 (old pattern was GET-then-DELETE/PATCH). Legacy items without `serverId` still work via a one-off GET fallback in `_findServerItemId()`. Don't strip the field thinking it's dead code.
- **`.product-bottle__img` uses `box-shadow` + `border-radius`, NOT `filter: drop-shadow`** — the bottle hero images (`bottle-{slug}.webp`) are full-frame photos with their own cream backdrop, so they render as a framed rectangular photo with a soft warm shadow below. The old `drop-shadow` filter was designed for cutout bottle-alone shots on white. If you ever swap back to cutout-style bottle images, revert to `filter: drop-shadow(0 12px 32px rgba(0,0,0,0.15))` — leaving `box-shadow` on a cutout PNG will render a weird rectangular halo around transparent pixels. Display width is `clamp(280px, 42vw, 480px)` to give the pedestal-and-props composition room to breathe.

- **Footer has three rows**: `.footer__social` (Instagram/TikTok) → `.footer__links` (Terms/Privacy Policy) → `.footer__legal` (copyright). When adding footer links, use `.footer__links`, not `.footer__social`.
- **Signup terms agreement**: `signup.html` has `.auth__agree` text below the submit button linking to `/terms` and `/privacy`. If adding new legal pages, consider whether they should be linked here too.
- **Legal pages share `.legal-*` CSS**: Both `terms.html` and `privacy.html` define identical `.legal-hero` / `.legal-body` / `.legal-section` styles inline. If adding another legal page, copy the same class system for visual consistency.
- **`style.css` cache-bust is at `?v=8`** — bump when editing `style.css`.

## Deployment (Railway)

- **Live URL**: https://web-production-cc74a0.up.railway.app
- **GitHub repo**: https://github.com/Maisonhenius/maison (public, lean ~46MB)
- **Railway project**: `maison-henius` (id: `f45a16f9-e777-4cce-abd1-dcd08c2ccb56`), service `web`, environment `b99a4d18-a9fc-4742-b874-c0b4d38e5ade`
- **Builder**: Dockerfile (clones from GitHub on Railway servers — bypasses upload size limits)
- **Deploy directory**: `/tmp/claude/maison-docker-deploy/` — ephemeral, recreated each session (see Redeploy steps)

### Redeploy

1. Push changes to `https://github.com/Maisonhenius/maison` `main` branch
2. Recreate deploy dir + Dockerfile (ephemeral — `/tmp` is wiped between sessions):
   ```bash
   mkdir -p /tmp/claude/maison-docker-deploy
   cat > /tmp/claude/maison-docker-deploy/Dockerfile << 'DEOF'
   FROM python:3.11-slim
   RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
   WORKDIR /app
   ARG CACHEBUST=1
   RUN git clone --depth 1 https://github.com/Maisonhenius/maison.git . && echo "bust=$CACHEBUST"
   RUN pip install --no-cache-dir -r requirements.txt
   WORKDIR /app/server
   EXPOSE 3000
   CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-3000}
   DEOF
   ```
3. Deploy: `cd /tmp/claude/maison-docker-deploy && railway up --project f45a16f9-e777-4cce-abd1-dcd08c2ccb56 --environment b99a4d18-a9fc-4742-b874-c0b4d38e5ade --service web --ci -m "<message>"`
4. Verify: `railway logs -n 15` — should show `Uvicorn running on http://0.0.0.0:8080`

### Still needed before custom domain

- **Stripe webhook secret** (currently `whsec_placeholder`) — create webhook in Stripe Dashboard pointing to `/api/stripe/webhook`, paste signing secret into Railway env
- **Custom domain** `maisonhenius.com` via `railway domain --custom`
- Replace `https://maisonhenius.com/` placeholder in `index.html` `og:image`
- Add `sitemap.xml`, proper `og:image` (1200x630 brand image)

## Image & Video Assets (WebP / H.264 only)

All product/landscape images in the deployed repo are WebP. Originals (PNG/JPG) stay local and are gitignored.

- **Tracked in git**: `assets/pictures/Collection & Fragrances/*.webp`, `assets/pictures/Jordan Landscape/*.webp`, `assets/pictures/ingredients/*.webp`, `assets/videos/web/*.mp4`, `assets/videos/web/*.webm` (hero brand-film + scroll-cinematic). The old `assets/video-frames/` directory and 121 WebP frames are gone — replaced by `scroll-cinematic.mp4`.
- **Gitignored** (originals only): `*.png`, `*.jpg`, `*.jpeg` in those folders, `assets/videos/*.mp4` (raw source videos), `assets/videos/web-original-backup/` (pre-encoding hero videos, kept locally for rollback)
- **Templates reference `.webp`** — never `.png`. PRODUCTS dict in `app.py` has 4 image fields:
  - `card_image`: Old square cards (1200x1200) — used in landing page collection + product Explore More grid
  - `mood_image`: New landscape scenes (1920x1072) — used in product page full-bleed Mood section only
  - `explore_image`: Legacy square variants (`card-*-square.webp`) — not currently referenced in templates
  - `bottle_image`: Bottle hero photos (1200x1490 portrait) — used in product page "The Bottle" section
- **Logotype asset**: `assets/images/logotype.webp` (800×873, 92KB, with alpha) — full crest + "Maison Henius" + "Collection Eaux de Parfums". Used in footer (`layout.html`) and auth pages (login, signup, admin/login). The old monogram SVG (`assets/images/logo.svg`) is still used in nav headers and favicons.

### Image size targets (don't ship oversized assets)

| Asset type | Max width | cwebp quality | Target file size | Notes |
|---|---|---|---|---|
| Card images (`card-*.webp`) | **1200px** | `-q 78` | 200-300 KB each | Display ~600px on screen, retina-ready |
| Bottle heroes (`bottle-{slug}.webp`) | **1200px** (portrait 4:5, 1200×1490) | `-q 80` | ~60-75 KB each | Cinematic still-life shots: bottle on travertine pedestal with ingredient props, warm cream backdrop. 4K JPEG masters live at `bottle-{slug}-hero-4k.png` (~7 MB each, gitignored) — keep locally for rollback / re-generation. Old bottle-alone shots (`Out of Control.webp` etc.) still exist in the folder but are no longer referenced in code. |
| Craft collection (story page) | **1004px** | `-q 80` | ~50 KB | 2x retina for 502px display frame |
| Story atelier (landing + story) | **1356px** | `-q 80` | ~175 KB | Full-width landscape banner |
| Ingredient images (`ingredients/*.webp`) | **800px** | `-q 80` | ~150 KB each | Square aspect for note grid |
| Jordan landscapes | ~1300px (current) | `-q 80` | ~150-200 KB | Already optimal |
| Scroll video frames | 1920×1080 (current) | `-q 92` | ~30-45 KB per frame, ~4.8 MB total | Don't shrink — canvas needs detail |

### Recipes

**Prereqs (macOS)**: `brew install webp` installs `cwebp` (Homebrew package is `webp`). `webpinfo` may still be absent — use `sips -g pixelWidth -g pixelHeight file.webp` to inspect dimensions.

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
6. **Editing product hero/card images** (e.g. swapping props): Pass the existing bottle/card image as input and describe what to replace. Works for swapping ingredients around the bottle while preserving the bottle, cap, composition, and lighting. Always regenerate BOTH bottle hero AND card image when props change.

Current AI-edited assets (with backups available): `patchouli.webp` (backup: `patchouli-wilted.webp`, 4K source: `patchouli-fresh-4k.webp`), `aldehydes.webp` (4K source: `aldehydes-nolabel-4k.webp`), `cool-spices.webp` (4K source: `cool-spices-4k.webp`), `coffee-with-cream.webp` (copy of `coffee.webp`), `moldavian-rose.webp` (copy of `rose.webp`), `coffee.webp` (backup: `coffee-beans.webp`), `card-parisian.webp` (backup: `card-parisian-original.webp`), `card-out-of-control.webp` (backup: `card-out-of-control-star-anise.webp`), `bottle-out-of-control.webp` (backup: `bottle-out-of-control-star-anise.webp`), `Maison Henius - universe.webp` (sibling of original `Maison Henius.webp`), `Story.webp` (backup: `Story-original.webp`, 4K source: `Story-edited.webp`), `craft-collection.webp` (4K source: `big-bottle-design-4k.webp`), **`bottle-{slug}.webp` × 5** for all products (4K JPEG masters at `bottle-{slug}-hero-4k.png`, gitignored; fallback is the original bottle-alone `{Product Name}.webp` still in folder). The bottle heroes were generated with the existing bottle as input-1 and `big-bottle-design-4k.webp` as the style-reference input-2 — that two-image pattern is what locked the Ionic cap + label fidelity while replacing the backdrop and adding travertine pedestal + ingredient props.

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

### Lighthouse Baseline (2026-04-14)

- **Accessibility: 100**, **Best Practices: 100**, **SEO: 100** — zero failed audits
- **LCP: ~1.1s** (logo SVG, bottleneck is Railway TTFB ~415ms + render delay ~565ms)
- **CLS: 0.00** — no layout shift
- **Key fixes applied**: `aria-label` on cart/auth links, `fetchpriority="high"` on logo, footer contrast ≥ 4.5:1, scroll FAB debounced with rAF
- **Remaining**: TTFB only improvable via Cloudflare CDN in front of Railway

## Stripe (current state)

- **Test mode** is active in production (test keys in Railway env)
- **Webhook not yet configured on production** — `STRIPE_WEBHOOK_SECRET=whsec_placeholder`. **The system still works** because `/checkout/success` is self-healing (verifies the Stripe session via API and calls `_create_order_from_stripe_session()` as a fallback). Configuring the webhook is still recommended for instant order creation (no dependency on the user landing on the success page) and for handling other Stripe events later.
- **Local testing**: `stripe listen --forward-to localhost:3000/api/stripe/webhook`. Local secret is in `.env.local`

## Future
- **Turbo Frames**: Cart badge, admin stats as independent frames
- **Turbo Streams**: Real-time admin updates via SSE
- **Stimulus Controllers**: Migrate inline scripts to proper controllers
- **Re-enable CI** — `.github/workflows/test.yml` was removed because it ran pytest from `server/`, but `server/tests/` and `server/requirements.txt` are gitignored. Re-adding requires either un-ignoring those files or writing a new workflow that hits the live URL after Railway deploys
