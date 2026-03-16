-- cre_tbl_t_topics.sql
-- t_topics テーブル定義

CREATE TABLE t_topics (
    id             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name           TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    important      BOOLEAN NOT NULL DEFAULT FALSE,
    joy            SMALLINT NOT NULL DEFAULT 0,
    anger          SMALLINT NOT NULL DEFAULT 0,
    sorrow         SMALLINT NOT NULL DEFAULT 0,
    fun            SMALLINT NOT NULL DEFAULT 0,
    emotion_total  SMALLINT GENERATED ALWAYS AS (
        joy + anger + sorrow + fun
    ) STORED,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at      TIMESTAMPTZ
);
