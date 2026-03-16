-- cre_tbl_t_session_topics.sql
-- t_session_topics テーブル定義

CREATE TABLE t_session_topics (
    session_id INTEGER NOT NULL REFERENCES t_sessions(id) ON DELETE CASCADE,
    topic_id   INTEGER NOT NULL REFERENCES t_topics(id) ON DELETE CASCADE,
    PRIMARY KEY (session_id, topic_id)
);
