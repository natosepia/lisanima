-- cre_idx_oauth.sql
-- OAuthテーブルのインデックス

-- 有効期限（GC・期限切れ判定用）
CREATE INDEX idx_t_oauth_access_token_expires ON t_oauth_access_token (expires_at);
CREATE INDEX idx_t_oauth_refresh_token_expires ON t_oauth_refresh_token (expires_at);
CREATE INDEX idx_t_oauth_auth_code_expires ON t_oauth_auth_code (expires_at);
CREATE INDEX idx_t_oauth_auth_session_expires ON t_oauth_auth_session (expires_at);

-- client_id（revoke_token の delete*ByClientId 用。FK参照元は自動index化されない）
CREATE INDEX idx_t_oauth_access_token_client_id ON t_oauth_access_token (client_id);
CREATE INDEX idx_t_oauth_refresh_token_client_id ON t_oauth_refresh_token (client_id);
CREATE INDEX idx_t_oauth_auth_code_client_id ON t_oauth_auth_code (client_id);
CREATE INDEX idx_t_oauth_auth_session_client_id ON t_oauth_auth_session (client_id);
