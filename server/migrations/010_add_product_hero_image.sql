-- Migration 010: per-product hero image
-- Run via: cd server && python migrations/run_migration.py 010_add_product_hero_image.sql
--
-- Adds an optional hero image to products. The product-page hero shows this image
-- when set, otherwise falls back to the existing `video`, otherwise an empty black
-- section. Existing rows get '' so their video hero is unchanged. Re-runnable.

ALTER TABLE products ADD COLUMN IF NOT EXISTS hero_image text NOT NULL DEFAULT '';
