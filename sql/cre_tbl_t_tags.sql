-- cre_tbl_t_tags.sql
-- t_tags テーブル定義

CREATE TABLE t_tags (
    id   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
