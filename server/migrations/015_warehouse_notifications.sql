-- 015 — Step 2: automatic emails (warehouse new-order email + owner issue alerts).
--
-- Additive only. Run once in the Supabase SQL editor.
-- Every table has RLS enabled and NO policies: only the website server (service
-- role) can read or write them.

-- Who receives the automatic "new order to fulfil" email (managed on Admin → Team access).
CREATE TABLE IF NOT EXISTS notification_recipients (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email       text NOT NULL UNIQUE,
  label       text NOT NULL DEFAULT '',
  active      boolean NOT NULL DEFAULT true,
  added_by    text NOT NULL DEFAULT '',
  created_at  timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE notification_recipients ENABLE ROW LEVEL SECURITY;

-- Every email attempt (sent / failed), so the owner can see delivery problems and resend.
CREATE TABLE IF NOT EXISTS notification_log (
  id            bigserial PRIMARY KEY,
  order_id      text,
  kind          text NOT NULL,                    -- warehouse_new_order | owner_issue
  recipient     text NOT NULL DEFAULT '',
  status        text NOT NULL CHECK (status IN ('sent', 'failed', 'skipped')),
  error         text NOT NULL DEFAULT '',
  provider_id   text NOT NULL DEFAULT '',         -- Resend message id
  triggered_by  text NOT NULL DEFAULT 'system',   -- system | owner email (manual resend)
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS notification_log_order_idx ON notification_log (order_id, created_at DESC);
ALTER TABLE notification_log ENABLE ROW LEVEL SECURITY;

-- Set once when the automatic warehouse email has gone out: prevents duplicates
-- (the webhook and the thank-you page can both confirm the same payment).
-- (Written as a DO block: the Supabase SQL editor rejects "ADD COLUMN IF NOT EXISTS".)
DO $$ BEGIN
  ALTER TABLE orders ADD COLUMN warehouse_notified_at timestamptz;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;
