-- 005_oauth_client_id_indexes.sql
-- t_oauth_* テーブルに client_id インデックスを追加する。
-- 既存運用DB向け差分マイグレーション（cre_idx_oauth.sql との差分を埋める）。
--
-- 背景:
--   revoke_token から delete*ByClientId() を呼ぶ際、client_id WHERE 句が
--   フルテーブル走査になっていた。PostgreSQL は FK 参照元に自動 index を
--   作成しないため、明示的に追加する。
--
-- 投入方法:
--   psql -d lisanima_db -U lisa -f migrations/005_oauth_client_id_indexes.sql

CREATE INDEX IF NOT EXISTS idx_t_oauth_access_token_client_id
    ON t_oauth_access_token (client_id);

CREATE INDEX IF NOT EXISTS idx_t_oauth_refresh_token_client_id
    ON t_oauth_refresh_token (client_id);

CREATE INDEX IF NOT EXISTS idx_t_oauth_auth_code_client_id
    ON t_oauth_auth_code (client_id);

CREATE INDEX IF NOT EXISTS idx_t_oauth_auth_session_client_id
    ON t_oauth_auth_session (client_id);
