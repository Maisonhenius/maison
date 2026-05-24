# Footer Social Links in CMS — Design Spec

**Date:** 2026-05-24
**Status:** Approved, in implementation

## Goal

Edit the footer's Instagram + TikTok + (new) LinkedIn URLs from `/admin/content/main`,
and individually show/hide each link. The footer renders on every page.

## Decisions

- Three networks only (Instagram, TikTok, LinkedIn). Not a generic link manager.
- Visibility = a real per-link on/off **toggle** (keeps the URL when hidden).
- LinkedIn ships **hidden + empty URL**; admin fills + enables it in the CMS.
- Instagram/TikTok keep their current URLs as defaults, visible on.

## Data model

New `"footer"` section in `PAGE_CONTENT_SCHEMA["main"]`, group "Footer — Social Links":

| field | type | default |
|---|---|---|
| `instagram_url` | text | `https://www.instagram.com/maisonhenius` |
| `instagram_visible` | toggle | `true` |
| `tiktok_url` | text | `https://www.tiktok.com/@maison.henius` |
| `tiktok_visible` | toggle | `true` |
| `linkedin_url` | text | `` (empty) |
| `linkedin_visible` | toggle | `false` |

Values stored as strings in `page_content` (toggles as `"true"`/`"false"`). No migration —
schema defaults drive the footer until the admin saves (same merge pattern as the GET API).

## New CMS field type: `toggle`

- `content_edit.html` `renderField`: render a checkbox for `field_type === 'toggle'`,
  initial checked = `(value || default) === 'true'`, `data-role="value-input"`.
- Save collector reads `el.checked ? 'true' : 'false'` for toggle inputs.
- GET/PUT API already type-agnostic (stores/returns `value` string + `field_type`).

## Global footer rendering (the key wrinkle)

`content()` is injected only into `/` and `/story`; the footer is global. So:

- Module cache `_FOOTER_SOCIAL` = list of `{name, label, url, visible}`, built by
  `reload_footer_social()` which merges `page_content` (page=main, section=footer) over
  the schema defaults.
- Register a Jinja **global** `footer_social` on `templates.env.globals` (same place as
  the existing filters) returning that list — available in ALL templates incl. `layout.html`.
- Refresh `reload_footer_social()` at startup (alongside products cache) and at the end of
  `PUT /api/admin/content/{page}` when `page == "main"`.
- `layout.html` `.footer__social`: loop `footer_social()`, render each `<a>` only when
  `visible AND url`. If none qualify, omit the row.

## Testing

- `reload_footer_social()` / the merge: defaults when unsaved; saved value overrides;
  toggle "false" hides; empty URL hides even if visible.
- Editor toggle round-trips ("true"/"false").

## Touched files

- `server/app.py` — schema, `_FOOTER_SOCIAL` + `reload_footer_social()`, Jinja global,
  startup hook, PUT refresh.
- `server/templates/admin/content_edit.html` — toggle field rendering + save.
- `server/templates/layout.html` — dynamic `.footer__social`.
- tests under `server/tests/`.
