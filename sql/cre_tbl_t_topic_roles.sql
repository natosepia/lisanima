-- cre_tbl_t_topic_roles.sql
-- t_topic_roles テーブル定義

CREATE TABLE t_topic_roles (
    topic_id INTEGER NOT NULL REFERENCES t_topics(id) ON DELETE CASCADE,
    role_id  INTEGER NOT NULL REFERENCES m_role(id) ON DELETE CASCADE,
    PRIMARY KEY (topic_id, role_id)
);
