-- Additive transition columns for authenticated Cloudinary delivery.
-- Apply before deploying code that writes/reads these fields.
-- This migration intentionally does not rewrite or delete legacy public URLs.

ALTER TABLE doctors
    ADD COLUMN IF NOT EXISTS mdcn_license_public_id VARCHAR NULL,
    ADD COLUMN IF NOT EXISTS mdcn_license_resource_type VARCHAR(16) NULL,
    ADD COLUMN IF NOT EXISTS mdcn_license_format VARCHAR(16) NULL,
    ADD COLUMN IF NOT EXISTS mdcn_license_delivery_type VARCHAR(16) NULL,
    ADD COLUMN IF NOT EXISTS indemnity_cert_public_id VARCHAR NULL,
    ADD COLUMN IF NOT EXISTS indemnity_cert_resource_type VARCHAR(16) NULL,
    ADD COLUMN IF NOT EXISTS indemnity_cert_format VARCHAR(16) NULL,
    ADD COLUMN IF NOT EXISTS indemnity_cert_delivery_type VARCHAR(16) NULL;

ALTER TABLE lab_results
    ADD COLUMN IF NOT EXISTS image_public_id VARCHAR NULL,
    ADD COLUMN IF NOT EXISTS image_resource_type VARCHAR(16) NULL,
    ADD COLUMN IF NOT EXISTS image_format VARCHAR(16) NULL,
    ADD COLUMN IF NOT EXISTS image_delivery_type VARCHAR(16) NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_doctors_mdcn_delivery_type'
    ) THEN
        ALTER TABLE doctors
            ADD CONSTRAINT ck_doctors_mdcn_delivery_type
            CHECK (
                mdcn_license_delivery_type IS NULL
                OR mdcn_license_delivery_type = 'authenticated'
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_doctors_indemnity_delivery_type'
    ) THEN
        ALTER TABLE doctors
            ADD CONSTRAINT ck_doctors_indemnity_delivery_type
            CHECK (
                indemnity_cert_delivery_type IS NULL
                OR indemnity_cert_delivery_type = 'authenticated'
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_lab_results_image_delivery_type'
    ) THEN
        ALTER TABLE lab_results
            ADD CONSTRAINT ck_lab_results_image_delivery_type
            CHECK (
                image_delivery_type IS NULL
                OR image_delivery_type = 'authenticated'
            );
    END IF;
END $$;
