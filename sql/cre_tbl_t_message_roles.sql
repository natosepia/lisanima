-- cre_tbl_t_message_roles.sql
-- t_message_roles テーブル定義（メッセージ×役割 N:N中間テーブル）

CREATE TABLE t_message_roles (
    message_id INTEGER NOT NULL REFERENCES t_messages(id) ON DELETE CASCADE,
    role_id    INTEGER NOT NULL REFERENCES m_role(id) ON DELETE RESTRICT,
    PRIMARY KEY (message_id, role_id)
);
