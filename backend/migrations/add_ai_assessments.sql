-- Apply before deploying Wave 3. Temporary data is deleted by the hourly cleanup.
CREATE TABLE IF NOT EXISTS ai_assessments (
    id VARCHAR(36) PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(16) NOT NULL CHECK (status IN ('ACTIVE','READY','COMPLETED','URGENT','CANCELLED','ABANDONED','EXPIRED')),
    presenting_concern TEXT NOT NULL,
    language VARCHAR(64) NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    state_version INTEGER NOT NULL DEFAULT 1,
    readiness BOOLEAN NOT NULL DEFAULT FALSE,
    readiness_reasons JSON NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    last_activity_at TIMESTAMPTZ NOT NULL,
    abandoned_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    originating_request_id VARCHAR(128) NOT NULL,
    latest_operation_id VARCHAR(128),
    source_summary_id VARCHAR(36),
    result_json JSON,
    last_response_json JSON,
    usage_committed BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_ai_assessments_patient_activity ON ai_assessments (patient_id, last_activity_at);
CREATE INDEX IF NOT EXISTS ix_ai_assessments_expires_at ON ai_assessments (expires_at);

CREATE TABLE IF NOT EXISTS ai_assessment_facts (
    id VARCHAR(36) PRIMARY KEY,
    assessment_id VARCHAR(36) NOT NULL REFERENCES ai_assessments(id) ON DELETE CASCADE,
    concept VARCHAR(64) NOT NULL,
    value TEXT NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('ASSERTED','DENIED','UNCERTAIN','UNKNOWN')),
    provenance VARCHAR(24) NOT NULL CHECK (provenance IN ('USER_STATED','MODEL_INFERENCE','ATTACHMENT_DERIVED','RETRIEVED_EVIDENCE')),
    source_turn_id VARCHAR(128),
    attachment_id VARCHAR(128),
    confidence INTEGER,
    created_at TIMESTAMPTZ NOT NULL,
    supersedes_fact_id VARCHAR(36) REFERENCES ai_assessment_facts(id)
);
CREATE INDEX IF NOT EXISTS ix_ai_assessment_facts_assessment_id ON ai_assessment_facts (assessment_id);

CREATE TABLE IF NOT EXISTS ai_assessment_questions (
    id VARCHAR(36) PRIMARY KEY,
    assessment_id VARCHAR(36) NOT NULL REFERENCES ai_assessments(id) ON DELETE CASCADE,
    concept VARCHAR(64) NOT NULL,
    semantic_key VARCHAR(100) NOT NULL,
    text TEXT NOT NULL,
    asked_at TIMESTAMPTZ NOT NULL,
    answered_at TIMESTAMPTZ,
    answer_turn_id VARCHAR(128),
    answer_status VARCHAR(16),
    answer_text TEXT,
    CONSTRAINT uq_ai_assessment_question_key UNIQUE (assessment_id, semantic_key)
);
CREATE INDEX IF NOT EXISTS ix_ai_assessment_questions_assessment_id ON ai_assessment_questions (assessment_id);
