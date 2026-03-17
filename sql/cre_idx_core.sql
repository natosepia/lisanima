-- cre_idx_core.sql
-- コアテーブル（t_messages, t_sessions, t_tags）のインデックス

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX idx_t_messages_content_trgm ON t_messages USING gin (content gin_trgm_ops);
CREATE INDEX idx_t_messages_speaker ON t_messages (speaker);
-- PostgreSQLはFK参照元に自動でインデックスを作成しないため明示的に定義
CREATE INDEX idx_t_messages_session_id ON t_messages (session_id);
CREATE INDEX idx_t_messages_created_at ON t_messages (created_at);
CREATE INDEX idx_t_messages_emotion_total ON t_messages (emotion_total);
CREATE INDEX idx_t_sessions_date ON t_sessions (date);
CREATE INDEX idx_t_tags_name_trgm ON t_tags USING gin (name gin_trgm_ops);
