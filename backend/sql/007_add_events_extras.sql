-- Add extra tracking fields (safe if not already present)
ALTER TABLE payment_events
  ADD COLUMN IF NOT EXISTS gateway TEXT,
  ADD COLUMN IF NOT EXISTS customer_email TEXT,
  ADD COLUMN IF NOT EXISTS customer_phone TEXT;

-- Recovery attempts table
CREATE TABLE IF NOT EXISTS recovery_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payment_event_id UUID NOT NULL REFERENCES payment_events(id) ON DELETE CASCADE,
    channel TEXT NOT NULL, -- e.g. 'whatsapp', 'email'
    attempt_time TIMESTAMPTZ DEFAULT now(),
    status TEXT DEFAULT 'pending',
    response TEXT
);
