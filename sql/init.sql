-- lisanima DDL
-- DB作成は手動実行済み: CREATE DATABASE lisanima_db;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- 既存テーブル
-- ============================================================

CREATE TABLE sessions (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    persona_id  TEXT NOT NULL DEFAULT 'lisa',
    date        DATE NOT NULL,
    session_seq INTEGER NOT NULL DEFAULT 1,
    project     TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at    TIMESTAMPTZ,
    UNIQUE(date, session_seq)
);

-- カテゴリマスタ（messagesより先に作成）
CREATE TABLE m_category (
    id   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

INSERT INTO m_category (name) VALUES
    ('session'),
    ('backlog'),
    ('knowledge'),
    ('discussion'),
    ('report');

CREATE TABLE messages (
    id             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id     INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    category       TEXT NOT NULL REFERENCES m_category(name),
    speaker        TEXT NOT NULL,
    target         TEXT,
    content        TEXT NOT NULL,
    emotion        INTEGER NOT NULL DEFAULT 0,
    emotion_total  INTEGER GENERATED ALWAYS AS (
        ((emotion >> 24) & 255) + ((emotion >> 16) & 255) + ((emotion >> 8) & 255) + (emotion & 255)
    ) STORED,
    source         TEXT,
    is_deleted     BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_reason TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE tags (
    id   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE message_tags (
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    tag_id     INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (message_id, tag_id)
);

-- ============================================================
-- OAuth 2.1テーブル
-- ============================================================

-- OAuthクライアント（動的登録されたクライアント情報）
CREATE TABLE m_oauth_client (
    client_id       TEXT PRIMARY KEY,
    client_info     JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 認可セッション（authorize() → /auth/pin 間の一時データ）
CREATE TABLE t_oauth_auth_session (
    session_id      TEXT PRIMARY KEY,
    client_id       TEXT NOT NULL REFERENCES m_oauth_client(client_id) ON DELETE CASCADE,
    redirect_uri    TEXT NOT NULL,
    state           TEXT,
    scopes          TEXT[] NOT NULL DEFAULT '{}',
    code_challenge  TEXT NOT NULL,
    code_challenge_method TEXT NOT NULL DEFAULT 'S256',
    redirect_uri_provided_explicitly BOOLEAN NOT NULL DEFAULT TRUE,
    resource        TEXT,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 認可コード（一時的、5分で失効、1回使い切り）
CREATE TABLE t_oauth_auth_code (
    code            TEXT PRIMARY KEY,
    client_id       TEXT NOT NULL REFERENCES m_oauth_client(client_id) ON DELETE CASCADE,
    redirect_uri    TEXT NOT NULL,
    redirect_uri_provided_explicitly BOOLEAN NOT NULL DEFAULT TRUE,
    code_challenge  TEXT NOT NULL,
    code_challenge_method TEXT NOT NULL DEFAULT 'S256',
    scopes          TEXT[] NOT NULL DEFAULT '{}',
    resource        TEXT,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- アクセストークン
CREATE TABLE t_oauth_access_token (
    token           TEXT PRIMARY KEY,
    client_id       TEXT NOT NULL REFERENCES m_oauth_client(client_id) ON DELETE CASCADE,
    scopes          TEXT[] NOT NULL DEFAULT '{}',
    resource        TEXT,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- リフレッシュトークン
CREATE TABLE t_oauth_refresh_token (
    token           TEXT PRIMARY KEY,
    client_id       TEXT NOT NULL REFERENCES m_oauth_client(client_id) ON DELETE CASCADE,
    scopes          TEXT[] NOT NULL DEFAULT '{}',
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- インデックス
-- ============================================================

-- 既存テーブル
CREATE INDEX idx_messages_content_trgm ON messages USING gin (content gin_trgm_ops);
CREATE INDEX idx_messages_speaker ON messages (speaker);
CREATE INDEX idx_messages_category ON messages (category);
CREATE INDEX idx_messages_session_id ON messages (session_id);
CREATE INDEX idx_messages_created_at ON messages (created_at);
CREATE INDEX idx_messages_emotion_total ON messages (emotion_total);
CREATE INDEX idx_sessions_date ON sessions (date);
CREATE INDEX idx_tags_name_trgm ON tags USING gin (name gin_trgm_ops);

-- OAuth用
CREATE INDEX idx_t_oauth_access_token_expires ON t_oauth_access_token (expires_at);
CREATE INDEX idx_t_oauth_refresh_token_expires ON t_oauth_refresh_token (expires_at);
CREATE INDEX idx_t_oauth_auth_code_expires ON t_oauth_auth_code (expires_at);
CREATE INDEX idx_t_oauth_auth_session_expires ON t_oauth_auth_session (expires_at);
