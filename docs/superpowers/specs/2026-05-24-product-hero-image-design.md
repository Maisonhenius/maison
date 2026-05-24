# Product Hero Image (image-or-video) — Design Spec

**Date:** 2026-05-24
**Status:** Approved, in implementation

## Goal

The product-page hero (currently a full-screen autoplay video) can be an **image OR a
video**, set per product in `/admin/products/{id}/edit`.

## Resolution order

`hero_image` (if set) → else `video` (if set) → else empty black section (unchanged).
"Image wins" in the rare both-set case (uploading an image is deliberate).

## Data model

Migration `010_add_product_hero_image.sql`: `ALTER TABLE products ADD COLUMN
hero_image text NOT NULL DEFAULT ''`. Holds a Supabase Storage URL (or legacy bare name),
resolved in templates via the existing `product_image` filter. Existing products keep
`hero_image=''`, so their video hero is unchanged.

## Backend

- `_row_to_product`: expose `hero_image`.
- `_validate_product_payload`: accept `hero_image` (optional, in the image-field loop).
- Create/update already flow through the validator + `reload_products_cache()`.

## Admin form (`product_form.html`)

- Add `hero_image` to `IMAGE_FIELDS` (drives the upload widget + edit-populate, both generic),
  label "Hero image (product-page background)", placed near the Hero video field.
- Add `hero_image` to the save payload (the payload lists image fields explicitly).

## Product page hero (`detail.html`)

```jinja
{% if product.hero_image %}
  <img class="product-hero__media" src="{{ product.hero_image | product_image }}" alt="{{ product.name }}">
{% elif product.video %}
  <video class="product-hero__media" autoplay muted loop playsinline preload="auto">
    <source src="{{ product.video | product_video }}" type="video/mp4">
  </video>
{% endif %}
```

- Rename the CSS selector `.product-hero__video` → `.product-hero__media` (shared cover
  styling for both img + video). Verify no JS references the old class first.
- Add `border-radius: 0` to `.product-hero__media` — the global `img { border-radius: 12px }`
  rule would otherwise round a full-bleed hero image (CLAUDE.md gotcha).
- Neither set → no media element; the section's `#0a0a08` background shows (unchanged).

## Testing

- `_row_to_product` includes `hero_image`; validator accepts/normalizes it.
- Hero renders image when `hero_image` set, video when only `video`, nothing (black) when neither.

## Touched files

- `server/migrations/010_add_product_hero_image.sql` (new)
- `server/app.py` — `_row_to_product`, `_validate_product_payload`
- `server/templates/admin/product_form.html` — IMAGE_FIELDS + payload
- `server/templates/products/detail.html` — hero markup + CSS
- tests under `server/tests/`
