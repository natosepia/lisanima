-- cre_tbl_m_oauth_client.sql
-- m_oauth_client テーブル定義

CREATE TABLE m_oauth_client (
    client_id       TEXT PRIMARY KEY,
    client_info     JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
