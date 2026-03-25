-- cre_idx_topic.sql
-- トピック系テーブル（t_topics）のインデックス

CREATE INDEX idx_t_topics_status ON t_topics (status);
CREATE INDEX idx_t_topics_name_trgm ON t_topics USING gin (name gin_trgm_ops);
CREATE INDEX idx_t_topics_emotion_total ON t_topics (emotion_total);

-- t_message_topics: topic_id側のFK参照元インデックス（message_id側はPKで効く）
CREATE INDEX idx_t_message_topics_topic_id ON t_message_topics (topic_id);

-- t_message_roles: role_id側のFK参照元インデックス（message_id側はPKで効く）
CREATE INDEX idx_t_message_roles_role_id ON t_message_roles (role_id);
