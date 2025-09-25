BEGIN;

-- Drop the broken version if it exists
DROP TABLE IF EXISTS recovery_attempts;

-- Recreate with columns that match your schema
CREATE TABLE recovery_attempts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  merchant_id UUID NOT NULL,                 -- matches merchants.id / payment_events.merchant_id
  razorpay_payment_id TEXT NOT NULL,         -- matches payment_events.razorpay_payment_id
  channel TEXT NOT NULL,                     -- 'whatsapp' | 'email' | 'sms'
  attempt_no INT NOT NULL,                   -- 1, 2, 3...
  scheduled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  sent_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'scheduled',  -- 'scheduled' | 'sent' | 'failed'
  error TEXT
);

-- Fast lookups
CREATE INDEX IF NOT EXISTS idx_attempts_mid_pid
  ON recovery_attempts (merchant_id, razorpay_payment_id);

COMMIT;
