---
name: Maison Henius
description: A house of memory and craftsmanship, rendered as the last warm hour of light over imperial sand.
colors:
  imperial-gold: "#e9db90"
  antique-gold: "#b8a44e"
  canyon-ochre: "#d4614b"
  desert-ink: "#0a0a08"
  atelier-ivory: "#faf9f6"
  warm-sand: "#f5f0e8"
  pure-white: "#ffffff"
  ash-gray: "#888888"
  hairline: "#dddddd"
  signal-error: "#c0392b"
  signal-success: "#587b3f"
typography:
  display:
    fontFamily: "Cormorant Garamond, Georgia, serif"
    fontSize: "clamp(2.8rem, 6vw, 5rem)"
    fontWeight: 300
    lineHeight: 1.05
    letterSpacing: "normal"
  headline:
    fontFamily: "Cormorant Garamond, Georgia, serif"
    fontSize: "clamp(1.6rem, 2.8vw, 2.4rem)"
    fontWeight: 300
    lineHeight: 1.2
    letterSpacing: "0.02em"
  title:
    fontFamily: "Cormorant Garamond, Georgia, serif"
    fontSize: "clamp(1.04rem, 1.44vw, 1.4rem)"
    fontWeight: 400
    lineHeight: 1.3
    letterSpacing: "0.28em"
  body:
    fontFamily: "Montserrat, system-ui, sans-serif"
    fontSize: "clamp(0.88rem, 1.05vw, 0.95rem)"
    fontWeight: 300
    lineHeight: 1.85
    letterSpacing: "0.02em"
  label:
    fontFamily: "Montserrat, system-ui, sans-serif"
    fontSize: "clamp(0.6rem, 0.9vw, 0.75rem)"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "0.25em"
rounded:
  sharp: "0"
  sm: "6px"
  md: "8px"
  lg: "12px"
  pill: "999px"
  full: "50%"
spacing:
  tight: "0.5rem"
  snug: "1rem"
  gutter: "1.5rem"
  section-inset: "clamp(1.5rem, 5vw, 4rem)"
  band: "3rem"
  chapter: "6rem"
components:
  button-cta:
    backgroundColor: "{colors.imperial-gold}"
    textColor: "{colors.desert-ink}"
    rounded: "{rounded.sharp}"
    padding: "0.8rem 2rem"
    typography: "{typography.label}"
  button-cta-hover:
    backgroundColor: "#d4c87a"
    textColor: "{colors.desert-ink}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.imperial-gold}"
    rounded: "{rounded.sharp}"
    padding: "1rem 1.8rem"
    typography: "{typography.label}"
  button-ghost-hover:
    backgroundColor: "{colors.imperial-gold}"
    textColor: "{colors.desert-ink}"
  input-line:
    backgroundColor: "transparent"
    textColor: "{colors.warm-sand}"
    rounded: "{rounded.sharp}"
    padding: "0.9rem 1.2rem"
    typography: "{typography.body}"
  chip-tab:
    backgroundColor: "transparent"
    textColor: "{colors.warm-sand}"
    rounded: "{rounded.sharp}"
    padding: "0.3rem 0"
    typography: "{typography.label}"
  card-product:
    backgroundColor: "{colors.desert-ink}"
    textColor: "{colors.warm-sand}"
    rounded: "{rounded.lg}"
    padding: "0"
---

# Design System: Maison Henius

## 1. Overview

**Creative North Star: "The Amber Hour"**

The interface is the last warm hour of light over imperial sand. A deep ink ground holds everything; a single gold glows rather than shines; cream reads like lamplight on stone. Nothing here is bright. Everything is lit. This is the visual translation of the house's promise that luxury is felt, not shown: the screen is calm, unhurried, and quietly confident, the way a bottle catches light on a dark shelf at dusk.

The system has two registers living in one house, and the order matters. The **brand surface** (landing, the scroll cinematic, the Universe and Story chapters) leads: full-bleed imagery, generous black space, serif headlines that breathe, and motion that unfolds the way a fragrance unfolds. Beneath it, the **commerce surface** (shop, cart, checkout, profile, admin) serves quietly: it borrows the same palette and type but allows itself a little more structure (softer corners, clearer affordances) so that buying never feels like a struggle. The commerce layer is never permitted to shout, badge, or rush. Handing over a bottle should feel like a gift in a beautifully lit room, not a transaction at a counter.

This system explicitly rejects three things. It is **not mass-market beauty retail**: no dense product walls, no sale banners, no star ratings, no urgency timers, no "Add to bag" counter energy. It is **not hype or drop culture**: no neon, no countdowns, no limited-drop loudness, nothing trendy. It is **not baroque heavy-luxury**: no gilded flourishes, no stacked heavy serifs, no luxury-by-shouting. The house earns its luxury through restraint, not gold leaf. The minimal, typographic, apothecary lane is acceptable territory, but only as long as it keeps the warm amber and ochre Jordanian soul. Minimalism must never turn clinical, cold, or white-lab.

**Key Characteristics:**
- Deep warm-ink ground; a single gold used as light, not decoration
- Cormorant Garamond serif (often italic, weight 300) over wide-tracked uppercase Montserrat
- Generous vertical rhythm and airy line-height (1.85+); silence is a material
- Sharp-cornered controls on the brand surface; soft 6-8px corners on commerce
- Motion that unfolds (GSAP mask reveals, scroll-driven scrub), never bounces
- The thin gold divider as a recurring signature gesture

## 2. Colors

A warm, muted palette of imperial sand at golden hour: a near-black ink, two golds, cream and stone, with ochre held in reserve. No tone is fully saturated and nothing is pure; warmth is tinted into every neutral.

### Primary
- **Imperial Gold** (#e9db90): The house's signal. The logo, the thin dividers, eyebrow labels, the solid commerce CTA, and the glow on hairline borders. It is light, not paint, used as a glow against dark. Its restraint is the point.
- **Antique Gold** (#b8a44e): The deeper, bronzed companion to Imperial Gold. Carries secondary CTAs (the ghost-to-fill explore buttons), active-state underlines, and warm-shadow undertones. Where Imperial Gold glows, Antique Gold grounds.

### Secondary
- **Canyon Ochre** (#d4614b): The Jordanian sandstone red of the packaging box, held in deliberate reserve. A rare accent for moments that reach for place and heritage. Never a UI workhorse; a single ember.

### Neutral
- **Desert Ink** (#0a0a08): The primary ground. A warm near-black, never `#000`. The dark room the gold is lit inside. Dominant background across brand surfaces.
- **Atelier Ivory** (#faf9f6): The light ground. Used for the bright editorial sections (product essence, legal pages) and label-plate surfaces. Warm, never clinical white.
- **Warm Sand** (#f5f0e8): The cream that doubles as text on dark and as a secondary light background. Most body copy on ink uses Warm Sand at reduced opacity (0.5-0.65), giving the soft lamplight-on-stone read.
- **Pure White** (#ffffff): Reserved, rare. Used only where maximum contrast is structurally required (icon strokes in nav). Never a background.
- **Ash Gray** (#888888): Muted UI text and meta on the commerce and admin surfaces (timestamps, secondary labels).
- **Hairline** (#dddddd): The faintest divider and border on light commerce surfaces.

### Functional
- **Signal Error** (#c0392b) and **Signal Success** (#587b3f): Strictly for form validation and order status on the commerce surface. Never decorative, never on the brand surface.

### Named Rules
**The Glow Rule.** Gold is light, not paint. Imperial Gold appears on roughly 10% or less of any brand screen, usually as a thin line, a small label, or a single hover fill. Flood a screen with gold and it stops glowing and starts gilding, which is the baroque failure this house rejects.

**The No-Pure-Black Rule.** Never `#000` as a brand surface. Desert Ink (#0a0a08) is the warm ground. The only places pure black appears are the cinematic void and icon strokes, both deliberate. Tint warmth into every neutral.

## 3. Typography

**Display Font:** Cormorant Garamond (with Georgia, serif fallback)
**Body Font:** Montserrat (with system-ui, sans-serif fallback)

**Character:** A high-contrast classical serif at light weight, frequently italic, paired with a quiet geometric sans set in wide uppercase tracking. The serif carries emotion and the narrative voice; the sans carries structure and labels. The pairing is airy, elegant, and unhurried, the typographic equivalent of generous space and soft light.

### Hierarchy
- **Display** (Cormorant, 300, clamp(2.8rem, 6vw, 5rem), line-height ~1.05): Hero and chapter openers only. One per view. Often italic. The held note.
- **Headline** (Cormorant, 300, clamp(1.6rem, 2.8vw, 2.4rem), line-height 1.2, 0.02em): Section headings across landing, story, and product pages. Italic is the house default for emotional headings.
- **Title** (Cormorant, 400, clamp(1.04rem, 1.44vw, 1.4rem), 0.28em, often uppercase): The wordmark and serif sub-heads. The widest tracking in the system; reserved for the brand name and formal labels.
- **Body** (Montserrat, 300, clamp(0.88rem, 1.05vw, 0.95rem), line-height 1.85, 0.02em): All running copy. Light weight, airy leading. On dark grounds, set in Warm Sand at 0.5-0.65 opacity, capped at 65-75ch.
- **Label** (Montserrat, 400, clamp(0.6rem, 0.9vw, 0.75rem), 0.25em, uppercase): Eyebrows, nav, CTAs, filter tabs, footer links. Wide tracking and small size; almost always uppercase, often Imperial Gold.

### Named Rules
**The Wide-Tracking Rule.** Uppercase Montserrat is always set with 0.2em-0.35em letter-spacing. Tight uppercase reads as a system UI; wide uppercase reads as engraving on a brass plate. The spacing is the luxury.

**The Italic-Emotion Rule.** When a heading carries feeling (a tagline, a chapter title, a fragrance promise), it is Cormorant italic at weight 300. When it carries structure (the wordmark, a section label), it is upright. Let the type's posture match its job.

## 4. Elevation

The system is flat by intent. Depth comes from tonal layering on the dark ground and from light, not from stacked drop-shadows. Brand surfaces have effectively no shadows; the sense of dimension comes from the warm ink, gradient scrims over imagery, and the glow of gold lines. The one deliberate exception is product photography, which carries a single warm, low, wide shadow so the bottle sits on its stone like a real object in real light. Commerce surfaces permit a whisper of ambient shadow on cards for affordance, nothing more.

### Shadow Vocabulary
- **Warm Pedestal** (`box-shadow: 0 24px 60px -20px rgba(60,40,10,0.18), 0 8px 20px -8px rgba(60,40,10,0.10)`): The bottle-hero shadow. Brown-tinted, never gray. Grounds product imagery as a physical object on stone.
- **Ambient Card** (`box-shadow: 0 1px 3px rgba(0,0,0,0.06)`): The faintest lift on commerce/admin cards, for affordance only.

### Glass (rare, purposeful)
`backdrop-filter: blur(8px-20px)` is permitted in exactly two roles: the floating circular controls (sound toggle, scroll-to-top FAB) and the full-screen mobile navigation overlay. It is never decorative chrome on cards or panels.

### Named Rules
**The Warm-Shadow Rule.** When a shadow is used, it is tinted brown/amber (rgba with warmth), never neutral gray. Gray shadows read as generic Material UI; warm shadows read as golden-hour light. Cool shadow on a warm palette is an instant tell.

## 5. Components

### Buttons
The house has exactly two button languages. Both are uppercase Label type with wide tracking and sharp corners on the brand surface.
- **Solid CTA (primary commerce):** Imperial Gold fill (#e9db90), Desert Ink text (#0a0a08), no border, padding 0.8rem 2rem. Hover deepens to #d4c87a. This is the high-intent action: Add to Cart, Checkout. The only place gold becomes a filled surface by default.
- **Ghost-to-Fill (editorial / secondary):** Transparent with a 1px gold border (Imperial or Antique Gold) and gold text. On hover the fill floods gold and the text flips to ink. Sharp corners, padding ~1rem 1.8rem. Used for contact, "explore more", and all secondary actions.
- **Disabled / out of stock:** Stone fill (#e6e3da), muted text (#8a877d). Quiet, never alarming.

### Filter Tabs (not chips)
Shop filters are minimal text tabs, not pills: transparent, no border, uppercase Label type at 0.25em, set in Warm Sand at 0.5 opacity. The active tab brightens to full Warm Sand with a 1px Antique Gold underline (`border-bottom`). Restraint over rounded-pill UI. (The pill radius (999px) is reserved for small badges and the stock indicator, not for filters.)

### Inputs / Fields
Borderless-line luxury fields. Transparent background, a single 1px gold border at low opacity (rgba(233,219,144,0.25)), Warm Sand text, sharp corners, padding 0.9rem 1.2rem. On focus the border simply brightens (to ~0.5 opacity). No glow, no fill, no shift. Placeholders are Warm Sand at 0.3 opacity. On mobile, font-size jumps to 16px to defeat iOS auto-zoom (mandatory, never removed).

### Cards / Containers
- **Corner Style:** Images carry the global 12px radius; commerce cards use 6-8px. Brand-surface content is largely uncontained (full-bleed, no card).
- **Background:** Desert Ink on dark sections, Atelier Ivory on light.
- **Shadow Strategy:** Flat by default; Ambient Card shadow only where affordance demands it. See Elevation.
- **Rule:** Cards are the exception, not the reflex. Most brand content needs no container; let black space and the gold divider do the framing.

### Navigation
Centered logo flanked by wide-tracked uppercase Label links (Montserrat 300, 0.25em), white on the transparent hero header, gold on hover. Below 768px the bar becomes a 3-column grid (hamburger / logo / icons) so the logo stays centered, and the menu opens as a full-screen blurred overlay with centered links. Touch targets are 44px minimum everywhere. The header floats over the hero (absolute, transparent), never a solid bar on the brand surface.

### Signature: The Gold Divider
A 40px-wide, 1px-tall Imperial Gold line, centered, that animates in via GSAP `scaleX` from 0. It marks the start of sections (contact, footer, story chapters). This single thin line is the house's most-repeated gesture: it does the work a heavy rule or a card border would do elsewhere, with a tenth of the weight.

## 6. Do's and Don'ts

### Do:
- **Do** treat gold as light. Keep Imperial Gold to ~10% of any brand screen (The Glow Rule): thin lines, small labels, one hover fill.
- **Do** ground every neutral in warmth. Desert Ink (#0a0a08) not `#000`; Atelier Ivory (#faf9f6) not pure white.
- **Do** set uppercase Montserrat with 0.2em-0.35em tracking. The space is the luxury (The Wide-Tracking Rule).
- **Do** let copy breathe: body line-height 1.85+, generous vertical rhythm, body capped at 65-75ch.
- **Do** use the thin gold divider to frame sections instead of boxes or heavy rules.
- **Do** keep shadows warm and rare (The Warm-Shadow Rule): brown-tinted, mostly just the bottle pedestal.
- **Do** let commerce serve quietly: softer 6-8px corners are allowed, but the palette, type, and calm are unchanged from the brand surface.

### Don't:
- **Don't** build mass-market beauty-retail energy: no dense product grids, sale banners, star ratings, urgency timers, or "Add to bag" counter loudness.
- **Don't** reach for hype or drop culture: no neon, no countdowns, no "limited drop" loudness, nothing trendy.
- **Don't** go baroque heavy-luxury: no gilded flourishes, no stacked heavy serifs, no flooding the screen with gold. The house earns luxury through restraint, not gold leaf.
- **Don't** let minimalism turn clinical: no clinical white, no cold gray shadows, no lab-stark stripping of the warm amber/ochre soul. Warmth is non-negotiable.
- **Don't** use gray drop-shadows on this warm palette; it reads as generic Material UI instantly.
- **Don't** add `border-left`/`border-right` color stripes, gradient text, or decorative glassmorphism. Glass is allowed only on the FAB controls and mobile nav overlay.
- **Don't** use bounce or elastic easing. Motion eases out and unfolds; it never springs.
- **Don't** wrap brand content in cards by reflex. Black space and the gold divider frame most things; nested cards are always wrong.
