-- Migration 009: per-product stock / inventory
-- Run via: cd server && python migrations/run_migration.py 009_add_product_stock.sql
--
-- Adds an integer stock count to products, backfills existing rows so the live
-- catalog stays purchasable at launch, and provides two race-safe single-statement
-- functions for decrement (on payment) and restock (on cancellation).
-- Re-runnable: backfill only touches NULLs, CHECK is dropped+re-added, functions
-- use CREATE OR REPLACE.

-- ── column ───────────────────────────────────────────────────────────────
-- Add nullable first so existing rows don't fail the NOT NULL, backfill, then lock.
ALTER TABLE products ADD COLUMN IF NOT EXISTS stock integer;

-- Backfill existing products to 50 (only rows that have never been set — keeps
-- admin-edited values intact if this migration is ever re-run).
UPDATE products SET stock = 50 WHERE stock IS NULL;

ALTER TABLE products ALTER COLUMN stock SET NOT NULL;
ALTER TABLE products ALTER COLUMN stock SET DEFAULT 0;

-- Never let stock go negative, even if application logic has a bug.
ALTER TABLE products DROP CONSTRAINT IF EXISTS products_stock_nonneg;
ALTER TABLE products ADD CONSTRAINT products_stock_nonneg CHECK (stock >= 0);

-- ── atomic decrement (on payment success) ─────────────────────────────────
-- Single UPDATE settles the race: only succeeds if enough stock remains.
-- Returns the new stock level, or NULL if there wasn't enough (caller decides
-- what to do — the purchase paths treat NULL as "oversold, fulfill anyway").
CREATE OR REPLACE FUNCTION decrement_stock(p_id text, p_qty int)
RETURNS int
LANGUAGE plpgsql
AS $$
DECLARE
  new_stock int;
BEGIN
  UPDATE products
     SET stock = stock - p_qty
   WHERE id = p_id
     AND stock >= p_qty
  RETURNING stock INTO new_stock;
  RETURN new_stock;  -- NULL when the row didn't match (insufficient stock)
END;
$$;

-- ── restock (on order cancellation) ────────────────────────────────────────
CREATE OR REPLACE FUNCTION restock(p_id text, p_qty int)
RETURNS int
LANGUAGE plpgsql
AS $$
DECLARE
  new_stock int;
BEGIN
  UPDATE products
     SET stock = stock + p_qty
   WHERE id = p_id
  RETURNING stock INTO new_stock;
  RETURN new_stock;
END;
$$;
