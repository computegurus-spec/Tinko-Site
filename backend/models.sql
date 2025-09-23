-- Enable UUIDs
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Merchants
CREATE TABLE IF NOT EXISTS merchants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  api_key TEXT UNIQUE NOT NULL,                -- used in webhook URL and dashboard auth
  upi_vpa TEXT,                                -- merchant's UPI ID for deep links
  razorpay_webhook_secret TEXT,                -- per-merchant Razorpay secret
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Payment events (failed/recovered)
CREATE TABLE IF NOT EXISTS payment_events (
  id BIGSERIAL PRIMARY KEY,
  merchant_id UUID REFERENCES merchants(id) ON DELETE CASCADE,
  razorpay_payment_id TEXT UNIQUE,
  customer_email TEXT,
  customer_phone TEXT,
  amount BIGINT,
  currency TEXT,
  status TEXT CHECK (status IN ('failed','recovered')),
  failure_reason TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_payment_events_merchant ON payment_events(merchant_id);
CREATE INDEX IF NOT EXISTS idx_payment_events_status ON payment_events(status);
