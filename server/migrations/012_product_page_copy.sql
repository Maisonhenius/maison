-- Migration 012: per-product editable page copy
-- Run via: cd server && python migrations/run_migration.py 012_product_page_copy.sql
--
-- Adds 8 NOT NULL text columns to products so the owner can edit, per fragrance,
-- the section labels and supporting copy that were previously hardcoded in
-- templates/products/detail.html (THE ESSENCE / THE WEARER / THE COMPOSITION /
-- THE BOTTLE blocks). Each column has a column-level DEFAULT matching the
-- string currently rendered, so existing rows + new rows land with sensible
-- starting text the owner can then refine in /admin/products/{id}/edit.
--
-- Re-runnable: ADD COLUMN IF NOT EXISTS, plus a guarded backfill that only
-- touches rows still holding the empty string.

-- ── columns (nullable first so existing rows survive, then backfill, then lock) ──
ALTER TABLE products ADD COLUMN IF NOT EXISTS essence_label         text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS essence_tagline       text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS wearer_label          text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS composition_label     text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS composition_subtitle  text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS bottle_label          text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS bottle_size           text;
ALTER TABLE products ADD COLUMN IF NOT EXISTS bottle_description    text;

-- Backfill existing rows. Only touches NULLs so admin-edited values stay intact
-- if this migration is ever re-run.
UPDATE products SET essence_label = 'The Essence' WHERE essence_label IS NULL;
UPDATE products SET essence_tagline =
  E'Our Essence does not seek to impress.\n\nIt seeks to resonate.'
  WHERE essence_tagline IS NULL;
UPDATE products SET wearer_label = 'The Wearer' WHERE wearer_label IS NULL;
UPDATE products SET composition_label = 'The Composition' WHERE composition_label IS NULL;
UPDATE products SET composition_subtitle = 'A journey in three acts' WHERE composition_subtitle IS NULL;
UPDATE products SET bottle_label = 'The Bottle' WHERE bottle_label IS NULL;
UPDATE products SET bottle_size = 'Eau de Parfum · 100ml' WHERE bottle_size IS NULL;
UPDATE products SET bottle_description =
  'Custom golden Zamac cap inspired by ancient Ionic columns. Amber glass with deep-to-golden gradient. Brass label plate with embossed detailing.'
  WHERE bottle_description IS NULL;

-- Lock NOT NULL + set column-level DEFAULTs so future inserts also land with
-- starting text (admin form does not need to populate these on create).
ALTER TABLE products ALTER COLUMN essence_label        SET NOT NULL;
ALTER TABLE products ALTER COLUMN essence_label        SET DEFAULT 'The Essence';

ALTER TABLE products ALTER COLUMN essence_tagline      SET NOT NULL;
ALTER TABLE products ALTER COLUMN essence_tagline      SET DEFAULT E'Our Essence does not seek to impress.\n\nIt seeks to resonate.';

ALTER TABLE products ALTER COLUMN wearer_label         SET NOT NULL;
ALTER TABLE products ALTER COLUMN wearer_label         SET DEFAULT 'The Wearer';

ALTER TABLE products ALTER COLUMN composition_label    SET NOT NULL;
ALTER TABLE products ALTER COLUMN composition_label    SET DEFAULT 'The Composition';

ALTER TABLE products ALTER COLUMN composition_subtitle SET NOT NULL;
ALTER TABLE products ALTER COLUMN composition_subtitle SET DEFAULT 'A journey in three acts';

ALTER TABLE products ALTER COLUMN bottle_label         SET NOT NULL;
ALTER TABLE products ALTER COLUMN bottle_label         SET DEFAULT 'The Bottle';

ALTER TABLE products ALTER COLUMN bottle_size          SET NOT NULL;
ALTER TABLE products ALTER COLUMN bottle_size          SET DEFAULT 'Eau de Parfum · 100ml';

ALTER TABLE products ALTER COLUMN bottle_description   SET NOT NULL;
ALTER TABLE products ALTER COLUMN bottle_description   SET DEFAULT 'Custom golden Zamac cap inspired by ancient Ionic columns. Amber glass with deep-to-golden gradient. Brass label plate with embossed detailing.';
