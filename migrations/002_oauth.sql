-- OAuth 2.1 テーブル追加 + m_category マスタ化 + messages.source 列追加
-- 実行対象: lisanima_db

BEGIN;

-- ============================================================
-- 1. m_category マスタテーブル（CHECK制約→FK化）
-- ============================================================
CREATE TABLE IF NOT EXISTS m_category (
    id   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

INSERT INTO m_category (name) VALUES
    ('session'),
    ('backlog'),
    ('knowledge'),
    ('discussion'),
    ('report')
ON CONFLICT (name) DO NOTHING;

-- messages.category に FK 追加（既存CHECK制約があれば先に削除）
DO $$
BEGIN
    -- CHECK制約があれば削除
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'messages'
          AND constraint_type = 'CHECK'
          AND constraint_name = 'messages_category_check'
    ) THEN
        ALTER TABLE messages DROP CONSTRAINT messages_category_check;
    END IF;
END $$;

-- FK追加（既存でなければ）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'messages'
          AND constraint_name = 'messages_category_fkey'
    ) THEN
        ALTER TABLE messages
            ADD CONSTRAINT messages_category_fkey
            FOREIGN KEY (category) REFERENCES m_category(name);
    END IF;
END $$;

-- ============================================================
-- 2. messages.source 列追加（MCPクライアント識別子）
-- ============================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'messages' AND column_name = 'source'
    ) THEN
        ALTER TABLE messages ADD COLUMN source TEXT;
    END IF;
END $$;

-- ============================================================
-- 3. OAuth 2.1 テーブル
-- ============================================================

-- OAuthクライアント（動的登録されたクライアント情報）
CREATE TABLE IF NOT EXISTS m_oauth_client (
    client_id       TEXT PRIMARY KEY,
    client_info     JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 認可セッション（authorize() → /auth/pin 間の一時データ）
CREATE TABLE IF NOT EXISTS t_oauth_auth_session (
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
CREATE TABLE IF NOT EXISTS t_oauth_auth_code (
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
CREATE TABLE IF NOT EXISTS t_oauth_access_token (
    token           TEXT PRIMARY KEY,
    client_id       TEXT NOT NULL REFERENCES m_oauth_client(client_id) ON DELETE CASCADE,
    scopes          TEXT[] NOT NULL DEFAULT '{}',
    resource        TEXT,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- リフレッシュトークン
CREATE TABLE IF NOT EXISTS t_oauth_refresh_token (
    token           TEXT PRIMARY KEY,
    client_id       TEXT NOT NULL REFERENCES m_oauth_client(client_id) ON DELETE CASCADE,
    scopes          TEXT[] NOT NULL DEFAULT '{}',
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 4. OAuth用インデックス
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_t_oauth_access_token_expires
    ON t_oauth_access_token (expires_at);

CREATE INDEX IF NOT EXISTS idx_t_oauth_refresh_token_expires
    ON t_oauth_refresh_token (expires_at);

CREATE INDEX IF NOT EXISTS idx_t_oauth_auth_code_expires
    ON t_oauth_auth_code (expires_at);

CREATE INDEX IF NOT EXISTS idx_t_oauth_auth_session_expires
    ON t_oauth_auth_session (expires_at);

COMMIT;
