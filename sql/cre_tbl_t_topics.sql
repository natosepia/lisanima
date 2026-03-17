-- cre_tbl_t_topics.sql
-- t_topics テーブル定義

CREATE TABLE t_topics (
    id             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name           TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    important      BOOLEAN NOT NULL DEFAULT FALSE,
    joy            SMALLINT NOT NULL DEFAULT 0 CHECK (joy BETWEEN 0 AND 255),
    anger          SMALLINT NOT NULL DEFAULT 0 CHECK (anger BETWEEN 0 AND 255),
    sorrow         SMALLINT NOT NULL DEFAULT 0 CHECK (sorrow BETWEEN 0 AND 255),
    fun            SMALLINT NOT NULL DEFAULT 0 CHECK (fun BETWEEN 0 AND 255),
    emotion_total  SMALLINT GENERATED ALWAYS AS (
        joy + anger + sorrow + fun
    ) STORED,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at      TIMESTAMPTZ
);
