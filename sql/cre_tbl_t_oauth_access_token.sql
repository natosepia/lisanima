-- cre_tbl_t_oauth_access_token.sql
-- t_oauth_access_token テーブル定義

CREATE TABLE t_oauth_access_token (
    token           TEXT PRIMARY KEY,
    client_id       TEXT NOT NULL REFERENCES m_oauth_client(client_id) ON DELETE CASCADE,
    scopes          TEXT[] NOT NULL DEFAULT '{}',
    resource        TEXT,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
