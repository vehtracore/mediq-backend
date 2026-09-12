-- Paystack renewal reconciliation and payload-free webhook idempotency.
-- Additive and safe for existing users: all new provider fields are nullable.

ALTER TABLE users ADD COLUMN IF NOT EXISTS paystack_customer_code VARCHAR NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS paystack_plan_code VARCHAR NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS paystack_environment VARCHAR NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS paystack_subscription_status VARCHAR NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS paystack_last_payment_reference VARCHAR NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS paystack_latest_invoice_code VARCHAR NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS paystack_current_period_start TIMESTAMP NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS paystack_current_period_end TIMESTAMP NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS paystack_next_payment_date TIMESTAMP NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS paystack_last_successful_payment_at TIMESTAMP NULL;

CREATE INDEX IF NOT EXISTS ix_users_paystack_customer_code
ON users (paystack_customer_code)
WHERE paystack_customer_code IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_users_paystack_last_payment_reference
ON users (paystack_last_payment_reference)
WHERE paystack_last_payment_reference IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_users_paystack_latest_invoice_code
ON users (paystack_latest_invoice_code)
WHERE paystack_latest_invoice_code IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_users_paystack_subscription_code
ON users (paystack_subscription_code)
WHERE paystack_subscription_code IS NOT NULL;

CREATE TABLE IF NOT EXISTS payment_events (
    id                    BIGSERIAL PRIMARY KEY,
    provider              VARCHAR(32)  NOT NULL,
    event_type            VARCHAR(80)  NOT NULL,
    provider_event_key    VARCHAR(255) NOT NULL,
    payment_key           VARCHAR(255) NULL,
    transaction_reference VARCHAR(255) NULL,
    subscription_code     VARCHAR(255) NULL,
    invoice_code          VARCHAR(255) NULL,
    user_id               INTEGER NULL,
    processing_status     VARCHAR(32)  NOT NULL DEFAULT 'processing',
    error_code            VARCHAR(80) NULL,
    received_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at          TIMESTAMPTZ NULL,
    processing_note       TEXT NULL,
    CONSTRAINT uq_payment_events_provider_event_key
        UNIQUE (provider, provider_event_key),
    CONSTRAINT uq_payment_events_provider_payment_key
        UNIQUE (provider, payment_key)
);

CREATE INDEX IF NOT EXISTS ix_payment_events_transaction_reference
ON payment_events (transaction_reference);
CREATE INDEX IF NOT EXISTS ix_payment_events_subscription_code
ON payment_events (subscription_code);
CREATE INDEX IF NOT EXISTS ix_payment_events_invoice_code
ON payment_events (invoice_code);
CREATE INDEX IF NOT EXISTS ix_payment_events_user_id
ON payment_events (user_id);

-- Backfill guidance (do not fabricate provider identifiers):
-- 1. Deploy this migration with nullable fields.
-- 2. Let verified subscription.create/invoice events populate real codes.
-- 3. For still-null legacy rows, export subscription/customer/plan mappings
--    from the Paystack test/live dashboard and update only after an operator
--    matches the existing subscription by account and environment.
