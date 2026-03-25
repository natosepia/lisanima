-- cre_tbl_t_message_topics.sql
-- t_message_topics テーブル定義（メッセージ×トピック N:N 中間テーブル）

CREATE TABLE t_message_topics (
    message_id INTEGER NOT NULL REFERENCES t_messages(id) ON DELETE CASCADE,
    topic_id   INTEGER NOT NULL REFERENCES t_topics(id) ON DELETE RESTRICT,
    PRIMARY KEY (message_id, topic_id)
);
