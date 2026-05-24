# Checkout "Coming Soon" Gate — Design Spec

**Date:** 2026-05-24
**Status:** Approved, in implementation

## Goal

Pre-launch gate: on `/checkout`, "Continue to Payment" shows a branded "arriving
soon, you'll be the first notified" modal instead of redirecting to Stripe. Must be
trivially turn-off-able for the real launch.

## Decisions (locked with stakeholder)

- **Off-switch:** a single backend constant `CHECKOUT_COMING_SOON` in `app.py`. Flip
  to `False` + redeploy → real checkout returns. Single source of truth.
- **No capture / no notify-list table:** checkout requires login, so everyone who
  reaches it is already a registered user. The launch notify-list = registered users.
  Nothing is saved on click; the modal is purely informational.

## Behavior

- **Flag ON (`True`):**
  - `/checkout` route passes `coming_soon=True` to `checkout.html`.
  - Clicking "Continue to Payment" opens the modal (intercepts the button click,
    no form submit, no Stripe redirect).
  - Defense in depth: `POST /api/checkout/create-session` short-circuits with
    `{"coming_soon": true}` (HTTP 200, no Stripe session) so checkout can't proceed
    even via a direct API hit.
- **Flag OFF (`False`):** checkout behaves exactly as today; modal never renders.

## Modal copy (on-brand)

> **Arriving Soon**
> Maison Henius is preparing for its official launch. As a registered member, you're
> already on the list — you'll be among the very first notified the moment the
> collection becomes available.
> *[ Close ]*

## Implementation

- `app.py`: `CHECKOUT_COMING_SOON = True` module constant (clear comment); `/checkout`
  route adds `coming_soon` to context; `create_checkout_session` guards at the top.
- `checkout.html`: hidden modal markup + on-brand CSS (ivory card, gold accents, dark
  overlay, Cormorant heading); JS reads the rendered flag, intercepts the submit button
  click → opens modal; close via button / overlay click / Esc. Normal submit path
  guarded too.

## Out of scope

No DB, no migration, no waitlist table, no email send. Just the flag + modal + guard.

## Touched files

- `server/app.py`
- `server/templates/checkout.html`
