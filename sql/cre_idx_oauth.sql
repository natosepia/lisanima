-- cre_idx_oauth.sql
-- OAuthテーブルのインデックス

CREATE INDEX idx_t_oauth_access_token_expires ON t_oauth_access_token (expires_at);
CREATE INDEX idx_t_oauth_refresh_token_expires ON t_oauth_refresh_token (expires_at);
CREATE INDEX idx_t_oauth_auth_code_expires ON t_oauth_auth_code (expires_at);
CREATE INDEX idx_t_oauth_auth_session_expires ON t_oauth_auth_session (expires_at);
