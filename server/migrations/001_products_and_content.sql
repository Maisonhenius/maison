-- Migration 001: products + page_content tables, RLS policies, indexes
-- Run via: python migrations/run_migration.py 001_products_and_content.sql

-- ============================================================================
-- products: e-commerce catalog, replaces hardcoded PRODUCTS dict in app.py
-- ============================================================================
CREATE TABLE IF NOT EXISTS products (
  id              text PRIMARY KEY,                 -- slug (e.g. 'out-of-control')
  slug            text NOT NULL UNIQUE,
  name            text NOT NULL,
  family          text NOT NULL,                    -- 'Floral-Gourmand', 'Woody-Amber', etc.
  price           numeric(10,2) NOT NULL,
  mood            text NOT NULL DEFAULT '',         -- short tagline ('Bold, daring, provocative')
  "character"     text NOT NULL DEFAULT '',         -- per-product story sentence
  description     text NOT NULL DEFAULT '',         -- brand boilerplate
  wearer          jsonb NOT NULL DEFAULT '[]'::jsonb,
  notes           jsonb NOT NULL DEFAULT '{}'::jsonb,
  card_image      text NOT NULL DEFAULT '',
  mood_image      text,
  explore_image   text,
  bottle_image    text NOT NULL DEFAULT '',
  video           text,
  is_hidden       boolean NOT NULL DEFAULT false,
  display_order   integer NOT NULL DEFAULT 0,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS products_visibility_order_idx
  ON products (is_hidden, display_order);

-- ============================================================================
-- page_content: editable text/image/video blocks for Main + Universe pages
-- ============================================================================
CREATE TABLE IF NOT EXISTS page_content (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  page            text NOT NULL,            -- 'main', 'universe'
  section         text NOT NULL,            -- 'hero', 'beginning', 'craft', etc.
  field           text NOT NULL,            -- 'headline', 'subhead', 'body', 'image', 'video'
  field_type      text NOT NULL,            -- 'text', 'image', 'video'
  value           text NOT NULL DEFAULT '',
  display_order   integer NOT NULL DEFAULT 0,
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (page, section, field)
);

CREATE INDEX IF NOT EXISTS page_content_page_section_idx
  ON page_content (page, section, display_order);

-- ============================================================================
-- updated_at trigger (re-bumps on every UPDATE)
-- ============================================================================
CREATE OR REPLACE FUNCTION bump_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS products_bump_updated_at ON products;
CREATE TRIGGER products_bump_updated_at
  BEFORE UPDATE ON products
  FOR EACH ROW EXECUTE FUNCTION bump_updated_at();

DROP TRIGGER IF EXISTS page_content_bump_updated_at ON page_content;
CREATE TRIGGER page_content_bump_updated_at
  BEFORE UPDATE ON page_content
  FOR EACH ROW EXECUTE FUNCTION bump_updated_at();

-- ============================================================================
-- Row-Level Security
-- Backend uses service-role key which BYPASSES RLS, so these policies only
-- gate direct client access (which the codebase doesn't currently do, but
-- this is defense in depth).
-- ============================================================================
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE page_content ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS products_public_read ON products;
CREATE POLICY products_public_read
  ON products FOR SELECT
  TO anon, authenticated
  USING (is_hidden = false);

DROP POLICY IF EXISTS page_content_public_read ON page_content;
CREATE POLICY page_content_public_read
  ON page_content FOR SELECT
  TO anon, authenticated
  USING (true);
