-- cre_tbl_t_message_tags.sql
-- t_message_tags テーブル定義

CREATE TABLE t_message_tags (
    message_id INTEGER NOT NULL REFERENCES t_messages(id) ON DELETE CASCADE,
    tag_id     INTEGER NOT NULL REFERENCES t_tags(id) ON DELETE RESTRICT,
    PRIMARY KEY (message_id, tag_id)
);
