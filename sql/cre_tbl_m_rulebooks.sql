-- cre_tbl_m_rulebooks.sql
-- m_rulebooks テーブル定義
-- Materialized Path形式でルールブックの階層構造を表現する

CREATE TABLE m_rulebooks (
    path        TEXT NOT NULL,                                          -- Materialized Path '1.2.3'
    version     INTEGER NOT NULL DEFAULT 1,
    level       SMALLINT NOT NULL CONSTRAINT m_rulebooks_level_chk
                    CHECK (level BETWEEN 1 AND 5),                      -- 階層Lv (1-5)
    content     TEXT NOT NULL,                                          -- Lv1-3: タイトル, Lv4: ルール本文
    reason      TEXT,
    is_retired  BOOLEAN NOT NULL DEFAULT FALSE,
    is_editable BOOLEAN NOT NULL DEFAULT TRUE,                          -- FALSE=constitutional (なとせのみ管理)
    persona_id  TEXT,                                                   -- 末端レベルのみ使用、上位はNULL、全員適用は '*'
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT m_rulebooks_pk PRIMARY KEY (path, version)
);
