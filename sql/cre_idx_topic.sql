-- cre_idx_topic.sql
-- トピック系テーブル（t_topics）のインデックス

CREATE INDEX idx_t_topics_status ON t_topics (status);
CREATE INDEX idx_t_topics_name_trgm ON t_topics USING gin (name gin_trgm_ops);
CREATE INDEX idx_t_topics_emotion_total ON t_topics (emotion_total);
