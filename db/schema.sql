CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    titulo TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN (
        'phishing', 'malware', 'acceso_no_autorizado', 'ddos', 'fuga_datos',
        'vulnerabilidad', 'uso_indebido', 'incidente_fisico', 'fraude', 'otro'
    )),
    severidad TEXT NOT NULL CHECK (severidad IN ('critica', 'alta', 'media', 'baja')),
    activo_afectado TEXT,
    confianza DOUBLE PRECISION NOT NULL CHECK (confianza BETWEEN 0 AND 1),
    origen TEXT NOT NULL CHECK (origen IN ('demo', 'langflow', 'fallback')),
    motivo_revision TEXT,
    recibido_at TIMESTAMPTZ NOT NULL,
    clasificado_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS assignments (
    report_id TEXT PRIMARY KEY REFERENCES reports(id),
    responsable TEXT NOT NULL,
    asignado_at TIMESTAMPTZ NOT NULL,
    vence_respuesta_at TIMESTAMPTZ NOT NULL,
    vence_resolucion_at TIMESTAMPTZ NOT NULL,
    respondido_at TIMESTAMPTZ,
    resuelto_at TIMESTAMPTZ,
    CHECK (vence_respuesta_at <= vence_resolucion_at),
    CHECK (resuelto_at IS NULL OR (respondido_at IS NOT NULL AND respondido_at <= resuelto_at))
);

CREATE TABLE IF NOT EXISTS bitacora (
    report_id TEXT NOT NULL REFERENCES reports(id),
    accion TEXT NOT NULL,
    actor TEXT NOT NULL,
    ocurrido_at TIMESTAMPTZ NOT NULL,
    detalle TEXT NOT NULL,
    PRIMARY KEY (report_id, accion)
);

CREATE INDEX IF NOT EXISTS reports_recibido_idx ON reports (recibido_at);
CREATE INDEX IF NOT EXISTS bitacora_accion_idx ON bitacora (accion, ocurrido_at);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CONSTRAINT users_role_check CHECK (role IN ('administrador', 'analista', 'gestor', 'auditor', 'solicitante')),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    token_version INTEGER NOT NULL DEFAULT 0,
    creado_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS report_requesters (
    report_id TEXT PRIMARY KEY REFERENCES reports(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS report_requesters_user_idx ON report_requesters (user_id);

CREATE TABLE IF NOT EXISTS request_notification_reads (
    user_id TEXT NOT NULL REFERENCES users(id),
    report_id TEXT NOT NULL,
    accion TEXT NOT NULL CHECK (accion IN ('asignado', 'responder', 'resolver')),
    read_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (user_id, report_id, accion),
    FOREIGN KEY (report_id, accion) REFERENCES bitacora(report_id, accion) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    jti TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS user_totp (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    secret TEXT,
    last_step BIGINT,
    pending_secret TEXT,
    pending_until BIGINT,
    pending_session TEXT
);

CREATE TABLE IF NOT EXISTS totp_recovery_codes (
    user_id TEXT NOT NULL REFERENCES user_totp(user_id) ON DELETE CASCADE,
    digest TEXT NOT NULL,
    PRIMARY KEY (user_id,digest)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    action TEXT NOT NULL,
    module TEXT NOT NULL,
    ip TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    phase TEXT NOT NULL,
    outcome TEXT,
    status_code INTEGER,
    entity_id TEXT,
    request_id TEXT
);

CREATE INDEX IF NOT EXISTS audit_time_idx ON audit_log (occurred_at);
CREATE INDEX IF NOT EXISTS audit_entity_idx ON audit_log (entity_id);

CREATE TABLE IF NOT EXISTS audit_visits (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    ip TEXT NOT NULL,
    module TEXT,
    sequence BIGINT NOT NULL,
    last_seen TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_visits_seen_idx ON audit_visits (last_seen);

CREATE TABLE IF NOT EXISTS rate_limits (
    bucket TEXT PRIMARY KEY,
    attempts INTEGER NOT NULL,
    expires_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS triage_baselines (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    sample_count INTEGER NOT NULL CHECK (sample_count > 0),
    average_seconds DOUBLE PRECISION NOT NULL CHECK (average_seconds > 0),
    samples_json TEXT NOT NULL DEFAULT '[]',
    is_demo INTEGER NOT NULL CHECK (is_demo IN (0,1)),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS triage_measurements (
    report_id TEXT PRIMARY KEY REFERENCES reports(id),
    elapsed_seconds DOUBLE PRECISION NOT NULL CHECK (elapsed_seconds >= 0),
    review_seconds DOUBLE PRECISION CHECK (review_seconds >= 0),
    baseline_id TEXT REFERENCES triage_baselines(id),
    measured_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS demo_impact_history (
    period TEXT PRIMARY KEY,
    report_count INTEGER NOT NULL CHECK (report_count > 0),
    response_on_time INTEGER NOT NULL CHECK (response_on_time >= 0 AND response_on_time <= report_count),
    resolution_on_time INTEGER NOT NULL CHECK (resolution_on_time >= 0 AND resolution_on_time <= report_count),
    manual_seconds DOUBLE PRECISION NOT NULL CHECK (manual_seconds > 0),
    automated_seconds DOUBLE PRECISION NOT NULL CHECK (automated_seconds >= 0),
    review_seconds DOUBLE PRECISION NOT NULL CHECK (review_seconds >= 0),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS impact_studies (
    id TEXT PRIMARY KEY,
    configuration TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS impact_observations (
    id TEXT PRIMARY KEY,
    study_id TEXT NOT NULL REFERENCES impact_studies(id),
    cohort TEXT NOT NULL CHECK (cohort IN ('manual','asistido')),
    reference TEXT NOT NULL,
    report_id TEXT REFERENCES reports(id) ON DELETE CASCADE,
    active_seconds DOUBLE PRECISION NOT NULL CHECK (active_seconds > 0),
    received_at TIMESTAMPTZ NOT NULL,
    answered_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    recorded_by TEXT NOT NULL REFERENCES users(id),
    recorded_at TIMESTAMPTZ NOT NULL,
    UNIQUE (study_id,cohort,reference),
    UNIQUE (study_id,report_id)
);

CREATE TABLE IF NOT EXISTS report_reviews (
    report_id TEXT PRIMARY KEY REFERENCES reports(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL,
    severidad TEXT NOT NULL,
    activo_afectado TEXT,
    reviewed_by TEXT NOT NULL,
    reviewed_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS login_failures (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    attempts INTEGER NOT NULL CHECK (attempts > 0),
    until_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS routing_versions (
    id TEXT PRIMARY KEY,
    configuration TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS report_routing_versions (
    report_id TEXT PRIMARY KEY REFERENCES reports(id) ON DELETE CASCADE,
    version_id TEXT NOT NULL REFERENCES routing_versions(id)
);

CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    activo INTEGER NOT NULL CHECK (activo IN (0,1)),
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS team_directory (
    nombre TEXT PRIMARY KEY,
    contacto TEXT NOT NULL,
    disponible INTEGER NOT NULL CHECK (disponible IN (0,1)),
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS report_comments (
    id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    contenido TEXT NOT NULL,
    author TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS report_attachments (
    id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    contenido BYTEA NOT NULL,
    tamano INTEGER NOT NULL,
    author TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_reads (
    report_id TEXT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    read_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (report_id,user_id)
);
CREATE TABLE IF NOT EXISTS report_ai_inputs (
    report_id TEXT PRIMARY KEY REFERENCES reports(id),
    payload TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
