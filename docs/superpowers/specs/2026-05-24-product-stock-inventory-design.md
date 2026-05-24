# Product Stock / Inventory — Design Spec

**Date:** 2026-05-24
**Status:** Approved, in implementation
**Branch:** main

## Goal

Track per-product inventory. Stock decreases as customers buy. At 0 a product is
"out of stock" (visible but unbuyable). A customer can never purchase more than is
available, and the **stock number is never shown to the customer anywhere** (display
constraint, hard rule).

## Decisions (locked with stakeholder)

1. **Decrement timing:** stock drops on **payment success** (`pending → confirmed`),
   not on the pre-created pending order. Best-effort availability check at checkout.
2. **Out-of-stock display:** product **stays visible** on shop/landing with an
   "Out of Stock" badge + disabled Add to Cart.
3. **Restock on cancel:** cancelling a confirmed/shipped/delivered order **auto-returns**
   the units to stock.
4. **Cart cap UX:** the cart `+` stepper **disables** at the available limit. No number,
   no error text, communicated via the disabled control.

## Out of scope (YAGNI)

No size/variant SKUs, no backorder/waitlist, no auto-reorder, no customer-visible
"only N left" counter. One integer `stock` per product.

## Data model

Migration `009_add_product_stock.sql`:

- `ALTER TABLE products ADD COLUMN stock integer NOT NULL DEFAULT 0`.
- `ALTER TABLE products ADD CONSTRAINT products_stock_nonneg CHECK (stock >= 0)`.
- Backfill existing rows to **50** (so the live catalog stays in stock at launch).
- Two race-safe Postgres functions (single-statement, so concurrent buyers can't both
  take the last unit):
  - `decrement_stock(p_id text, p_qty int) returns int` — `UPDATE products SET stock = stock - p_qty WHERE id = p_id AND stock >= p_qty RETURNING stock`. Returns `NULL` if insufficient.
  - `restock(p_id text, p_qty int) returns int` — `UPDATE products SET stock = stock + p_qty WHERE id = p_id RETURNING stock`.

## Keeping the number hidden

The raw count lives server-side + admin only. Customer side never receives the integer:

- Server-rendered templates use a derived **`in_stock` boolean** (`stock > 0`), never the count.
- Cart API responses carry a per-item **`at_max` boolean** (cart qty ≥ available). The
  `+` button disables on that boolean. No number sent to the client.

## Stock lifecycle

- **Decrement** in `_confirm_order` (idempotent via existing status guard) and in the
  Case-3 fallback create inside `_create_order_from_stripe_session`. Loops items, calls
  `decrement_stock` per line.
- **Oversell safety net:** if `decrement_stock` returns `NULL` (raced to sold out) the
  customer already paid — never reject. Clamp stock to 0 and log an oversell flag for admin.
  Payment always wins.
- **Restock** in `update_order_status`: read the order's prior status first; if
  transitioning to `cancelled` from `confirmed`/`shipped`/`delivered`, call `restock` per
  item. Skip if already cancelled (no double-restock) and skip pending (never decremented).

## The four anti-oversell gates

| Gate | Behavior |
|------|----------|
| Product detail Add to Cart | `stock=0` → server-rendered disabled "Out of Stock". Cart already at max → server caps, subtle toast (no number). |
| Cart `+` stepper | disables at limit via `at_max`. |
| `POST /api/cart`, `PATCH /api/cart/{id}` | clamp quantity to available; return items with `at_max`. |
| `POST /api/checkout/create-session` | hard re-validate; reject over-stock items with "no longer available in the requested quantity" (no number). |

## Customer UI

- Shop grid, landing collection cards, product explore cards: "Out of Stock" badge +
  greyed disabled CTA when `not in_stock`. Brand gold/ivory styling, `border-radius` aware.
- Guest (logged-out) carts can't cap client-side (no number sent); capped at login/checkout.

## Admin UI

- `product_form.html`: required "Stock" number input (≥ 0), red asterisk like other
  required fields. Wired into create + edit payloads.
- `products.html`: Stock column. Low-stock highlight: amber when `≤ 5`, red "Out of stock"
  when `0`.
- `_validate_product_payload`: `stock` int ≥ 0; required on create.

## Testing

- decrement on confirm; no decrement on pending/abandoned.
- restock on cancel; no double-restock; no restock from pending.
- checkout rejection when qty > stock.
- cart clamp + `at_max`.
- out-of-stock template branch renders badge + disabled CTA.

## Touched files

- `server/migrations/009_add_product_stock.sql` (new)
- `server/app.py` — `_row_to_product`, `_validate_product_payload`, `_confirm_order`,
  `_create_order_from_stripe_session`, `create_checkout_session`, `add_to_cart`,
  `update_cart_item`, `get_cart`, `sync_cart`, `update_order_status`
- `server/templates/admin/product_form.html`, `server/templates/admin/products.html`
- `server/templates/shop.html`, `server/templates/index.html`, `server/templates/products/detail.html`
- `js/cart.js`, `css/style.css` (badge + disabled styles)
- tests under `server/tests/`
