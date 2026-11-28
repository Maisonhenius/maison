-- 016 — Step 3: shipping zones, door-to-door fee, taxes per delivery country,
-- and the separate charge amounts stored on each order.
--
-- Additive only. Run once in the Supabase SQL editor (safe to run again).
-- Written without "ADD COLUMN IF NOT EXISTS" (the SQL editor rejects it).
-- RLS on, no policies: only the website server reads and writes these tables.

-- Zones: a group of delivery countries with the fees the CUSTOMER pays.
CREATE TABLE IF NOT EXISTS shipping_zones (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name              text NOT NULL,
  countries         text[] NOT NULL DEFAULT '{}',          -- ISO codes, e.g. {AE,SA}
  shipping_fee      numeric(10,2) NOT NULL DEFAULT 0 CHECK (shipping_fee >= 0),
  door_to_door_fee  numeric(10,2) NOT NULL DEFAULT 0 CHECK (door_to_door_fee >= 0),
  additional_fee    numeric(10,2) NOT NULL DEFAULT 0 CHECK (additional_fee >= 0),
  additional_label  text NOT NULL DEFAULT 'Additional charges',
  active            boolean NOT NULL DEFAULT true,
  sort              integer NOT NULL DEFAULT 0,
  updated_by        text NOT NULL DEFAULT '',
  updated_at        timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE shipping_zones ENABLE ROW LEVEL SECURITY;

-- Tax by DELIVERY country (owner decision). Rate 0 = no tax line.
CREATE TABLE IF NOT EXISTS country_taxes (
  country              text PRIMARY KEY,                    -- ISO code
  tax_name             text NOT NULL DEFAULT 'VAT',
  rate                 numeric(5,2) NOT NULL DEFAULT 0 CHECK (rate >= 0 AND rate <= 100),
  applies_to_delivery  boolean NOT NULL DEFAULT true,       -- tax also on shipping + door-to-door + additional
  updated_by           text NOT NULL DEFAULT '',
  updated_at           timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE country_taxes ENABLE ROW LEVEL SECURITY;

-- The charges each order was sold with (copied at payment; later rate changes never alter them).
DO $$ BEGIN ALTER TABLE orders ADD COLUMN door_to_door_fee numeric(10,2) NOT NULL DEFAULT 0;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE orders ADD COLUMN additional_fee numeric(10,2) NOT NULL DEFAULT 0;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE orders ADD COLUMN additional_label text NOT NULL DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE orders ADD COLUMN tax_amount numeric(10,2) NOT NULL DEFAULT 0;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE orders ADD COLUMN tax_label text NOT NULL DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE orders ADD COLUMN discount_amount numeric(10,2) NOT NULL DEFAULT 0;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE orders ADD COLUMN shipping_zone text NOT NULL DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- Starting point = today's pricing (USD 25 shipping to every country, nothing else),
-- so the checkout charges exactly what it does now until the owner edits the zones.
INSERT INTO shipping_zones (name, countries, shipping_fee, door_to_door_fee, additional_fee, sort, updated_by)
SELECT 'All countries (current flat rate)',
       ARRAY['JO','AE','SA','KW','BH','OM','QA','LB','EG','US','GB','FR','DE'],
       25, 0, 0, 0, 'migration 016'
WHERE NOT EXISTS (SELECT 1 FROM shipping_zones);
