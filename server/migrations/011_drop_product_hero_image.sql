-- Migration 011: drop products.hero_image (reverts 010)
-- Run via: cd server && python migrations/run_migration.py 011_drop_product_hero_image.sql
--
-- The hero is a SINGLE media field: the existing `video` column holds either an
-- image or a video URL, and the product page renders <img> or <video> based on the
-- file extension. The separate hero_image column (010) is no longer used.

ALTER TABLE products DROP COLUMN IF EXISTS hero_image;
