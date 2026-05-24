# Product

## Register

brand

## Users

The connoisseur, not the crowd. Someone who reads a fragrance the way others read a novel: for the unfolding, not the label. They have lived across places and cultures, value craftsmanship they can feel (the weight of glass, the emboss of a brass plate), and buy scent as memory rather than commodity. They arrive on the site in a quiet, unhurried moment, often on a phone, often at night, browsing for the pleasure of it before they ever reach a cart.

Primary markets are Jordan (origin) and the UAE (expansion), with travel-retail and selective international perfumery as the growth horizon. The audience is "the few who understand" addressed in a welcoming way, never an exclusive or arrogant one.

## Product Purpose

Maison Henius is a niche luxury perfume house built on a single idea: fragrance is not worn, it is lived. The collection, Beyond Borders, is five Eau de Parfums born from the contrast at the heart of Jordan: fragrant gardens meeting the mineral vastness of the desert.

The website is the house's flagship door. It must do three things at once, in this order:

1. **Make people feel the house before they shop it.** The cinematic hero film, the scroll-driven cap-onto-bottle reveal, and the Universe and Story pages exist to transmit atmosphere, memory, and craft. This is the product.
2. **Sell, without breaking the spell.** A real store sits underneath (shop, cart, Stripe checkout, accounts, admin). Commerce is essential but subordinate: it should feel like being handed a bottle in a beautifully lit room, not like checking out at a counter.
3. **Build a community and capture its data** for selective, high-end campaigns over the three-year position-accelerate-grow arc.

Success is a visitor who leaves having felt something, and returns because of it. Conversion follows belief, not the reverse.

## Brand Personality

Three words: **elegant, warm, timeless.**

- **Voice:** narrative and poetic. Sentences flow like storytelling and invite the reader into a journey. Sensory and evocative (amber glow, golden silence, textured elegance), confidently minimal, chosen with precision. Inclusive yet exclusive: speak to the few who understand, warmly.
- **Emotional goals:** calm, depth, quiet confidence, the warmth of imperial sands. Luxury that is felt, not shown.
- **Use the words:** elegance, refinement, artistry, craftsmanship, amber, ochre, gold, warmth, timeless, enduring, essence, memory, emotion, journey, harmony, rare, cultivated, noble.
- **Never the words:** sacred, ritual, confidential, magical, mysterious, forbidden, trendy, flashy, hype, affordable. No religious or secretive framing, no mass-market commercial register, no overpromising superlatives, no stacked adjectives.
- **House line:** "You live the memories." / "Fragrance is not worn. It is lived." / "You do not buy a fragrance. You enter a story."

## Anti-references

What this must never look like:

- **Mass-market beauty retail** (Sephora, Ulta, department-store grids). No dense product walls, sale banners, star ratings, urgency badges, or "Add to bag" counter energy. Selective and calm is the whole point; a busy storefront destroys it.
- **Hype / drop culture** (streetwear-collab fragrance). No neon, no countdown timers, no "limited drop" loudness, no gen-z maximalism. BRAND.md rejects "trendy" outright.
- **Baroque heavy-luxury** (Creed, old-Tom-Ford gold-on-black maximalism). No ornate gilded flourishes, no heavy serifs stacked everywhere, no luxury-by-shouting. The house earns its luxury through restraint, not gold leaf.

Acceptable adjacent territory: the calm, typographic, minimal apothecary lane (Aesop, Le Labo) is *not* off-limits, but it must keep the warm amber and ochre Jordanian soul. Never let minimalism turn clinical, cold, or white-lab. Warmth is non-negotiable.

## Design Principles

1. **Atmosphere before information.** The first job of any screen is to make the visitor feel the house. Lead with mood, light, and motion; let copy and product detail unfold from there, the way the fragrances themselves unfold.
2. **Luxury is felt, not shown.** Restraint signals confidence. Generous space, muted warm tones, one considered gesture beats ten decorations. If an element is shouting, it is wrong.
3. **Commerce serves the story.** Cart, checkout, and admin must work flawlessly and quietly. Never let a conversion pattern (urgency, badges, upsell clutter) puncture the calm. Handing over a bottle should feel like a gift, not a transaction.
4. **Memory over product, emotion over visibility.** Every choice should deepen the connection to memory and place (garden and desert, amber and stone), not maximize visibility or noise. We are not the loudest tab open.
5. **Craft is in the detail.** The weight of a transition, the warmth of a shadow, the tactility of travertine and brass in the imagery. The house's promise of craftsmanship lives or dies in the small things, so they are never afterthoughts.

## Accessibility & Inclusion

- **Baseline:** Lighthouse Accessibility 100, maintained. Aim for WCAG 2.1 AA on the storefront and commerce paths (the parts where exclusion would actually cost a customer the experience).
- **Touch targets ≥ 44×44px**, enforced across nav icons, hamburger, cart steppers, auth buttons, and product CTAs. Mobile-first; tested at 320×568, 375×812, and 768.
- **No `user-scalable=no`.** Pinch-zoom stays. iOS 16px input rule prevents auto-zoom without disabling it.
- **Color contrast ≥ 4.5:1** for body text and footer, verified.
- **Conscious exception:** the scroll cinematic runs for all viewers regardless of OS "Reduce motion" (WCAG 2.3.3 AAA non-compliance, by design). The scrub is brand-critical. Worst case degrades to a static black void, never a crash. This is the one place identity outranks the guideline, and it is deliberate, not an oversight.
