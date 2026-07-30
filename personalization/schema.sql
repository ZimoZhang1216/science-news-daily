PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    email TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'expired')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_profiles (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    is_current INTEGER NOT NULL CHECK (is_current IN (0, 1)),
    base_profile TEXT NOT NULL,
    research_topic TEXT NOT NULL,
    include_keywords_json TEXT NOT NULL,
    exclude_keywords_json TEXT NOT NULL,
    source_ids_json TEXT NOT NULL,
    source_layer_ids_json TEXT NOT NULL DEFAULT '[]',
    journal_ids_json TEXT NOT NULL,
    content_preferences_json TEXT NOT NULL,
    max_items INTEGER NOT NULL,
    lookback_days INTEGER NOT NULL DEFAULT 3,
    ccf_conference_tiers_json TEXT NOT NULL DEFAULT '["A", "B"]',
    llm_provider TEXT NOT NULL,
    llm_model TEXT NOT NULL,
    output_formats_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, version)
);

CREATE TABLE IF NOT EXISTS schedules (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    frequency TEXT NOT NULL CHECK (frequency IN ('daily', 'weekdays', 'weekly')),
    weekday INTEGER,
    timezone TEXT NOT NULL,
    local_send_time TEXT NOT NULL,
    next_run_at TEXT NOT NULL,
    last_run_at TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS report_runs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    profile_version INTEGER NOT NULL,
    report_date TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('automatic', 'manual')),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'preview_ready', 'completed', 'failed')),
    github_run_id TEXT NOT NULL DEFAULT '',
    github_run_url TEXT NOT NULL DEFAULT '',
    artifact_name TEXT NOT NULL DEFAULT '',
    artifact_expires_at TEXT NOT NULL DEFAULT '',
    candidate_count INTEGER NOT NULL DEFAULT 0,
    matched_count INTEGER NOT NULL DEFAULT 0,
    deduplicated_count INTEGER NOT NULL DEFAULT 0,
    history_excluded_count INTEGER NOT NULL DEFAULT 0,
    selected_count INTEGER NOT NULL DEFAULT 0,
    ai_generated INTEGER NOT NULL DEFAULT 0,
    profile_filter_fallback INTEGER NOT NULL DEFAULT 0,
    metrics_recorded_at TEXT NOT NULL DEFAULT '',
    error_summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS deliveries (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    report_run_id TEXT NOT NULL REFERENCES report_runs(id) ON DELETE CASCADE,
    profile_version INTEGER NOT NULL,
    report_date TEXT NOT NULL,
    channel TEXT NOT NULL CHECK (channel = 'email'),
    mode TEXT NOT NULL CHECK (mode IN ('automatic', 'manual')),
    status TEXT NOT NULL CHECK (status IN ('queued', 'claimed', 'preview_ready', 'sending', 'sent', 'retryable_failed', 'failed', 'cancelled')),
    idempotency_key TEXT NOT NULL UNIQUE,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    artifact_name TEXT NOT NULL DEFAULT '',
    artifact_run_id TEXT NOT NULL DEFAULT '',
    sent_at TEXT NOT NULL DEFAULT '',
    schedule_id TEXT NOT NULL DEFAULT '',
    schedule_period_key TEXT NOT NULL DEFAULT '',
    locked_at TEXT NOT NULL DEFAULT '',
    locked_by TEXT NOT NULL DEFAULT '',
    execution_id TEXT NOT NULL DEFAULT '',
    last_attempt_at TEXT NOT NULL DEFAULT '',
    next_retry_at TEXT NOT NULL DEFAULT '',
    error_stage TEXT NOT NULL DEFAULT '',
    email_prepared_at TEXT NOT NULL DEFAULT '',
    email_sending_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS report_items (
    id TEXT PRIMARY KEY,
    report_run_id TEXT NOT NULL REFERENCES report_runs(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    report_date TEXT NOT NULL,
    profile_version INTEGER NOT NULL,
    doi TEXT NOT NULL DEFAULT '',
    link TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    published_at TEXT NOT NULL DEFAULT '',
    score REAL NOT NULL DEFAULT 0,
    identity_keys_json TEXT NOT NULL,
    title_key TEXT NOT NULL DEFAULT '',
    topic_key TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS run_events (
    id TEXT PRIMARY KEY,
    report_run_id TEXT NOT NULL REFERENCES report_runs(id) ON DELETE CASCADE,
    delivery_id TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_metrics (
    id TEXT PRIMARY KEY,
    report_run_id TEXT NOT NULL REFERENCES report_runs(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    source_id TEXT NOT NULL DEFAULT '',
    source_layer TEXT NOT NULL DEFAULT 'academic_research',
    credibility INTEGER NOT NULL DEFAULT 0,
    success INTEGER NOT NULL CHECK (success IN (0, 1)),
    item_count INTEGER NOT NULL DEFAULT 0,
    matched_count INTEGER NOT NULL DEFAULT 0,
    deduplicated_count INTEGER NOT NULL DEFAULT 0,
    selected_count INTEGER NOT NULL DEFAULT 0,
    error_summary TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_schedules_next_run_at ON schedules(next_run_at);
CREATE INDEX IF NOT EXISTS idx_deliveries_status_updated_at ON deliveries(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_deliveries_retry ON deliveries(mode, status, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_report_items_user_date ON report_items(user_id, report_date);
CREATE INDEX IF NOT EXISTS idx_report_runs_user_date ON report_runs(user_id, report_date);
