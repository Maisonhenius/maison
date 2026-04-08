-- Migration: add phone column to addresses table
-- Date: 2026-04-08
-- Why: Profile address form now collects phone (matches checkout form pattern).
--      Also enables auto-saving the first checkout address — including phone —
--      to the user's profile if they have no saved addresses yet.
--
-- How to run: Open Supabase dashboard → SQL Editor → paste → Run.
-- Idempotent (uses IF NOT EXISTS) — safe to re-run.

ALTER TABLE addresses ADD COLUMN IF NOT EXISTS phone TEXT;
