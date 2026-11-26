-- 014 — Team access (warehouse / fulfilment role) + manual order fulfilment.
--
-- Additive only: new tables, new nullable/defaulted columns. Nothing existing is
-- dropped or renamed, so the previous code keeps working against this schema.
--
-- Security model: every table here has RLS enabled and NO policies, so the
-- public anon key and logged-in users (incl. warehouse staff) cannot read or
-- write them through Supabase directly. Only the website server (service role)
-- touches them, and it enforces the roles in app.py (_resolve_staff).

-- ── Staff accounts (owners stay hard-coded in ALLOWED_EMAILS as a safety net) ──
CREATE TABLE IF NOT EXISTS staff_accounts (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid UNIQUE,                       -- auth.users.id
  email         text NOT NULL UNIQUE,
  full_name     text NOT NULL DEFAULT '',
  company       text NOT NULL DEFAULT '',
  role          text NOT NULL DEFAULT 'fulfilment' CHECK (role IN ('fulfilment', 'admin')),
  status        text NOT NULL DEFAULT 'invited'    CHECK (status IN ('invited', 'active', 'suspended', 'revoked')),
  invited_by    text NOT NULL DEFAULT '',
  invited_at    timestamptz NOT NULL DEFAULT now(),
  activated_at  timestamptz,
  last_seen_at  timestamptz,
  updated_at    timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE staff_accounts ENABLE ROW LEVEL SECURITY;

-- ── Staff activity log (sign-ins, order views, refused requests, team changes) ──
CREATE TABLE IF NOT EXISTS staff_activity (
  id          bigserial PRIMARY KEY,
  staff_email text NOT NULL DEFAULT '',
  role        text NOT NULL DEFAULT '',
  action      text NOT NULL,
  detail      text NOT NULL DEFAULT '',
  ip          text NOT NULL DEFAULT '',
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS staff_activity_created_idx ON staff_activity (created_at DESC);
ALTER TABLE staff_activity ENABLE ROW LEVEL SECURITY;

-- ── Order history (append-only: who changed what, when, before/after) ──
CREATE TABLE IF NOT EXISTS order_events (
  id          bigserial PRIMARY KEY,
  order_id    text NOT NULL,
  actor_email text NOT NULL DEFAULT '',
  actor_name  text NOT NULL DEFAULT '',
  actor_role  text NOT NULL DEFAULT '',           -- owner | admin | fulfilment | system
  action      text NOT NULL,                      -- status | shipment | issue | issue_resolved | comment | payment
  from_value  text,
  to_value    text,
  details     jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS order_events_order_idx ON order_events (order_id, created_at);
ALTER TABLE order_events ENABLE ROW LEVEL SECURITY;

-- History can be added to but never edited or deleted (applies to the service role too).
CREATE OR REPLACE FUNCTION order_events_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'order_events is append-only';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS order_events_no_change ON order_events;
CREATE TRIGGER order_events_no_change BEFORE UPDATE OR DELETE ON order_events
  FOR EACH ROW EXECUTE FUNCTION order_events_append_only();

-- ── Fulfilment fields on orders ──
ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS fulfilment_status      text NOT NULL DEFAULT 'new',
  ADD COLUMN IF NOT EXISTS courier                text,
  ADD COLUMN IF NOT EXISTS shipping_method        text,
  ADD COLUMN IF NOT EXISTS tracking_number        text,
  ADD COLUMN IF NOT EXISTS shipment_ref           text,
  ADD COLUMN IF NOT EXISTS dispatch_date          date,
  ADD COLUMN IF NOT EXISTS expected_delivery      text,
  ADD COLUMN IF NOT EXISTS actual_shipping_cost   numeric(10,2),
  ADD COLUMN IF NOT EXISTS actual_additional_cost numeric(10,2),
  ADD COLUMN IF NOT EXISTS issue_type             text,
  ADD COLUMN IF NOT EXISTS issue_note             text,
  ADD COLUMN IF NOT EXISTS issue_raised_by        text,
  ADD COLUMN IF NOT EXISTS issue_raised_at        timestamptz,
  ADD COLUMN IF NOT EXISTS dispatched_at          timestamptz,
  ADD COLUMN IF NOT EXISTS delivered_at           timestamptz,
  ADD COLUMN IF NOT EXISTS fulfilment_updated_at  timestamptz;

DO $$ BEGIN
  ALTER TABLE orders ADD CONSTRAINT orders_fulfilment_status_check
    CHECK (fulfilment_status IN ('new', 'received', 'preparing', 'packed', 'dispatched', 'delivered'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  ALTER TABLE orders ADD CONSTRAINT orders_actual_costs_check
    CHECK (coalesce(actual_shipping_cost, 0) >= 0 AND coalesce(actual_additional_cost, 0) >= 0);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Existing orders: line the new fulfilment status up with what already happened.
UPDATE orders SET fulfilment_status = 'dispatched' WHERE status = 'shipped'   AND fulfilment_status = 'new';
UPDATE orders SET fulfilment_status = 'delivered'  WHERE status = 'delivered' AND fulfilment_status = 'new';

CREATE INDEX IF NOT EXISTS orders_fulfilment_idx ON orders (status, fulfilment_status, created_at DESC);

-- ── Warehouse reference code on products ──
ALTER TABLE products ADD COLUMN IF NOT EXISTS sku text NOT NULL DEFAULT '';

-- ── Stock movements (every change to a product's stock, with the reason) ──
-- Applied rows are permanent. Warehouse requests ("received" / "damaged") start
-- as 'pending' and only change the stock once an owner approves them on the
-- Stock page; a pending row can be decided once, never edited afterwards.
CREATE TABLE IF NOT EXISTS stock_movements (
  id             bigserial PRIMARY KEY,
  product_id     text NOT NULL,
  product_name   text NOT NULL DEFAULT '',
  kind           text NOT NULL CHECK (kind IN ('opening', 'sale', 'cancel_return', 'adjustment', 'received', 'damaged')),
  quantity       integer NOT NULL,                 -- signed change: + in, - out
  stock_after    integer,                          -- level right after; NULL while pending / if rejected
  status         text NOT NULL DEFAULT 'applied' CHECK (status IN ('applied', 'pending', 'rejected')),
  reason         text NOT NULL DEFAULT '',
  order_id       text,
  actor_email    text NOT NULL DEFAULT '',
  actor_name     text NOT NULL DEFAULT '',
  actor_role     text NOT NULL DEFAULT '',
  decided_by     text,
  decided_at     timestamptz,
  decision_note  text,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS stock_movements_product_idx ON stock_movements (product_id, created_at DESC);
CREATE INDEX IF NOT EXISTS stock_movements_pending_idx ON stock_movements (status) WHERE status = 'pending';
ALTER TABLE stock_movements ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION stock_movements_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' OR OLD.status <> 'pending' THEN
    RAISE EXCEPTION 'stock_movements: only a pending request can be decided, nothing can be deleted';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS stock_movements_guard ON stock_movements;
CREATE TRIGGER stock_movements_guard BEFORE UPDATE OR DELETE ON stock_movements
  FOR EACH ROW EXECUTE FUNCTION stock_movements_guard();

-- Starting point for the history: today's level of every product.
INSERT INTO stock_movements (product_id, product_name, kind, quantity, stock_after, reason, actor_name, actor_role)
SELECT p.id, p.name, 'opening', p.stock, p.stock, 'Stock level when the stock history started', 'System', 'system'
FROM products p
WHERE NOT EXISTS (SELECT 1 FROM stock_movements s WHERE s.product_id = p.id);
