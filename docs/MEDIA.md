# Media: Scroll Cinematic, Image/Video Encoding

Referenced from `CLAUDE.md`. The asset-location map, the 4 product image fields, the
Jinja filter resolution rules, and the critical "don't revert to canvas" trap stay in
CLAUDE.md (auto-loaded). This file holds the deep architecture + the encoding recipes you
only need when you're actually re-encoding a file.

---

## Scroll Cinematic (`<video>` element + `currentTime` scrub)

`assets/videos/web/scroll-cinematic.mp4` — a ~5s Seedance-generated cap-onto-bottle reveal on a pure `#000` void background. 1920×1080 H.264 High profile / yuv420p / faststart / no audio / **all-intra (every frame is a keyframe)** / 3.33 MB. Re-encoded from the gitignored source `assets/videos/scroll-video-3.mp4`. The MP4 is committed; the source MP4 is gitignored.

- **All-intra encoding is REQUIRED, not optional.** With default H.264 GOP (1 keyframe per file), every `currentTime` seek forces the decoder to walk forward from t=0 — 30-80ms per seek on mid-tier hardware, visible as scroll glitching / frame-stick / "video doesn't track scroll smoothly." With every-frame-keyframe encoding, each seek decodes one independent I-frame in <1ms regardless of position. File grows ~4× (~3 MB vs ~800 KB) but it's a 5-second clip. **Use the recipe below; don't omit `keyint=1:min-keyint=1:scenecut=0`.**

**Why `<video>` + `currentTime` and NOT canvas + frames:** the prior canvas implementation preloaded all 121 WebP frames as ImageBitmaps in JS heap (1920×1080 × 4 bytes × 121 = ~1 GB of decoded RGBA). iOS Safari per-tab memory budget is ~120-400 MB depending on device, so EVERY iPhone OOM-killed the tab and showed "A problem repeatedly occurred" (or Chrome iOS's "Can't open this page" — Chrome iOS is WebKit too). The video element pushes decoding into the browser's hardware video pipeline, capping memory at ~30 MB regardless of length. Same source video, same 1920×1080 pixels, same 5-second timeline, same scrub feel — bulletproof on every device.

- **HTML**: `<video class="scroll-video__media" muted playsinline webkit-playsinline preload="auto" disableRemotePlayback aria-hidden="true">` inside `.scroll-video__sticky`. `muted` + `playsinline` is the iOS-blessed combination for inline rendering without autoplay; we never call `play()` because `currentTime` updates render frames on a paused video just fine. `disableRemotePlayback` removes the "Stream to AirPlay" UI from Safari.
- **Cover-fit + MOBILE_SCALE in CSS**: `object-fit: cover` does the cover-fit math the canvas implementation did manually. `@media (orientation: portrait) { transform: scale(0.72) }` does the MOBILE_SCALE multiplier — same 0.72 value, same goal (keep the cap + bottle subject visible on tall phones where straight cover-fit clips the sides). Pure `#000` sticky bg hides the resulting bands.
- **JS scrub** (~30 lines, in `index.html`): `ScrollTrigger.create({ ..., onUpdate: function(self) { targetTime = self.progress * video.duration; requestAnimationFrame(applyScrub); } })`. The `requestAnimationFrame` wrapper coalesces rapid scroll deltas — without it, mobile touch scroll fires `onUpdate` faster than the video can seek. `applyScrub` no-ops when `Math.abs(video.currentTime - targetTime) < 0.001` to avoid redundant seeks.
- **First-frame paint**: `video.currentTime = 0.001` is set on `loadeddata` to force iOS Safari to decode and render the first frame BEFORE any scroll happens. Without this nudge, the `<video>` element renders transparent until the first user-driven `currentTime` change. The 0.001s offset is invisible (the cap-alone hero frame is at t=0).
- **Scroll distance is tapered** (CSS): `400vh` desktop, `300vh` under 768px, `250vh` under 480px (3-screen-tall scrubs feel interminable on a phone).
- **Section + sticky backgrounds are pure `#000`** (not brand `#0a0a08`) so the `MOBILE_SCALE` letterbox bars are visually invisible.
- **No `prefers-reduced-motion` fallback.** The scroll scrub is brand-critical and runs for all viewers regardless of OS "Reduce motion" setting. WCAG 2.3.3 AAA non-compliance is a conscious choice.
- **No poster image, no preloaded image.** Per user direction "always a video, never an image": the section's `#000` background covers the brief moment before the video metadata loads (~50-200 ms). The scroll cinematic is BELOW the fold, so any metadata-load delay is invisible in normal usage.
- **iOS Low Power Mode**: `currentTime` updates render frames even when iOS LPM blocks autoplay (LPM blocks `play()` specifically, not seek-driven rendering). Verified WebKit behavior. Worst case if LPM somehow does block: section shows pure `#000`, user scrolls past, no crash.

### Three runtime traps (also condensed inline in CLAUDE.md Gotchas)

- **ScrollTrigger MUST be created synchronously**, NOT gated on `loadedmetadata`. A starved video (hero LCP preload hogging bandwidth) means metadata never arrives, the section never pins, and the user scrolls right past. Create the trigger immediately on IIFE run; inside `onUpdate`, guard `targetTime` math with `isFinite(video.duration) && video.duration > 0`. Pinning works without video; scrubbing kicks in once duration becomes finite.
- **iOS Safari does NOT render `currentTime` updates on a paused video that has never played.** WebKit ignores seek-driven frame updates until the video has been kicked into "play mode" once. Workaround: `video.play().then(() => { video.pause(); video.currentTime = 0.001; })`. The IIFE primes it this way via IntersectionObserver one viewport before the section approaches (avoids competing with hero LCP autoplay). Without this prime, iOS users see the section pin but the video stays on frame 0 forever.
- **`<link rel="preload" as="video" fetchpriority="high">` can starve other below-fold videos.** The preload scanner serializes resource fetches when a high-priority asset is in flight: the hero loads fine but the scroll-cinematic's `loadedmetadata` never fires until the hero finishes. DON'T add high-priority preloads for both hero and scroll-cinematic — pick one.

### Re-encode the cinematic from source

```bash
ffmpeg -y -i assets/videos/scroll-video-3.mp4 \
  -c:v libx264 -preset slow -crf 22 \
  -profile:v high -level 4.0 \
  -pix_fmt yuv420p \
  -x264-params keyint=1:min-keyint=1:scenecut=0 \
  -an \
  -movflags +faststart \
  assets/videos/web/scroll-cinematic.mp4
```

**Why these flags**: H.264 Main profile + Level 4.0 + yuv420p = universal Safari/iOS compatibility (avoids High 10 / 422 chroma profiles that break iOS playback). `-an` strips audio. `+faststart` puts the moov atom at the start of the file so the browser can begin decoding before the full file arrives — critical for HTTP range-request streaming. CRF 22 is visually transparent quality.

---

## Hero video (silent + separate audio) — full detail

Condensed trap is in CLAUDE.md Gotchas; the reasoning lives here.

`assets/videos/web/brand-film-silent.{mp4,webm}` are the autoplaying hero video (audio stripped via `ffmpeg -c:v copy -an`); `brand-film-audio.m4a` is the standalone audio (extracted via `ffmpeg -vn -c:a copy`).

- **Why split**: macOS Safari blocks autoplay of any video that contains an audio track, even when `muted` is set, on low-engagement sites — the play-button overlay stays. Stripping the audio track entirely makes autoplay structurally impossible to block (silent videos always autoplay).
- **Source order is MP4 first, WebM second** so Safari grabs H.264 directly without trying VP9+Opus (which it stalls on).
- JS calls `heroVideo.play().catch()` on `loadeddata` to bypass Safari's autoplay-attribute timing — without it Safari waits for `canplaythrough` instead of `canplay`, adding a multi-second delay on a 9 MB film.
- Sound toggle plays/pauses `<audio id="heroAudio" loop>`; on first activation it sets `heroAudio.currentTime = heroVideo.currentTime % heroAudio.duration` so audio starts at the visual moment the user is currently seeing. Both loop independently (~62s each); minor drift is imperceptible.
- Original `web/brand-film.{mp4,webm}` (with audio) were deleted from git after the split. Source file (`assets/videos/Brand film.mp4`, 124 MB) is gitignored.
- **`.m4a` MIME type**: `mimetypes.add_type("audio/mp4", ".m4a")` runs at import in `app.py`. Without it, Python's default registry on Linux emits `audio/mp4a-latm` which some browsers/CDNs reject.

---

## Image size targets (don't ship oversized assets)

| Asset type | Max width | cwebp quality | Target file size | Notes |
|---|---|---|---|---|
| Card images (`card-*.webp`) | **1200px** | `-q 78` | 200-300 KB each | Display ~600px on screen, retina-ready |
| Bottle heroes (`bottle-{slug}.webp`) | **1200px** (portrait 4:5, 1200×1490) | `-q 80` | ~60-75 KB each | Cinematic still-life: bottle on travertine pedestal w/ ingredient props, warm cream backdrop. 4K JPEG masters at `bottle-{slug}-hero-4k.png` (~7 MB each, gitignored). Old bottle-alone shots (`Out of Control.webp` etc.) still in folder but unreferenced. |
| Craft collection (story page) | **1004px** | `-q 80` | ~50 KB | 2x retina for 502px display frame |
| Story atelier (landing + story) | **1356px** | `-q 80` | ~175 KB | Full-width landscape banner |
| Ingredient images (`ingredients/*.webp`) | **800px** | `-q 80` | ~150 KB each | Square aspect for note grid |
| Jordan landscapes | ~1300px (current) | `-q 80` | ~150-200 KB | Already optimal |
| Scroll video frames (legacy) | 1920×1080 | `-q 92` | ~30-45 KB/frame | Frame era is over (see Scroll Cinematic above) |

## Encoding recipes

**Prereqs (macOS)**: `brew install webp` installs `cwebp` (Homebrew package is `webp`). `webpinfo` may be absent — use `sips -g pixelWidth -g pixelHeight file.webp` to inspect dimensions.

```bash
# Card image (4K source → 1200px web)
cwebp -q 78 -resize 1200 0 input.png -o output.webp

# Ingredient (any source → 800px square)
cwebp -q 80 -resize 800 0 input.png -o output.webp

# Hero video (1080p source → 720p H.264 ~1 Mbps, no audio, streamable)
ffmpeg -y -i input.mp4 -c:v libx264 -preset slow -crf 26 -vf "scale=1280:-2" -an -movflags +faststart output.mp4
```

- **Always check dimensions before encoding** — `cwebp` doesn't auto-resize. Forget `-resize WIDTH 0` and you ship a 4K image displayed at 600px, wasting ~1 MB/file (happened with cards originally, encoded at 4096×4096 → ~7 MB on every landing paint). Verify with `webpinfo file.webp` (or `sips`).
- **Long-form video (brand film, 60s+)**: VP9 single-pass CRF doesn't beat H.264 CRF 26 for file size (VP9 CRF 32 = 11 MB vs H.264 8.83 MB). Use **VP9 2-pass at target bitrate** (~800 kbps for 720p) to match H.264 quality at ~30% smaller. H.264 long-form recipe: `-preset veryslow -tune film -crf 26`. Verify: `ffprobe -v error -show_entries stream=codec_type,codec_name,bit_rate -of default=noprint_wrappers=1 file.{mp4,webm}`.
