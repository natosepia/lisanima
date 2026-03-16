-- cre_tbl_t_oauth_auth_code.sql
-- t_oauth_auth_code テーブル定義

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
