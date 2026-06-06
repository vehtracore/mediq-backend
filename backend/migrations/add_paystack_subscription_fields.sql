-- Migration: add_paystack_subscription_fields
-- Date: 2026-06-06
-- Adds two nullable VARCHAR columns to the users table to persist the
-- Paystack recurring-subscription identifiers needed for cancellation.
--
-- paystack_subscription_code : The "SUB_xxxx" code Paystack returns in the
--                               subscription.create webhook. Required to call
--                               POST /subscription/disable.
-- paystack_email_token        : The short-lived token Paystack includes
--                               alongside the subscription code. Required as
--                               the second factor when disabling a subscription.
--
-- Safe to run multiple times — the IF NOT EXISTS guard prevents errors on
-- re-runs or deployments that already applied this migration manually.

ALTER TABLE users ADD COLUMN IF NOT EXISTS paystack_subscription_code VARCHAR;
ALTER TABLE users ADD COLUMN IF NOT EXISTS paystack_email_token VARCHAR;
