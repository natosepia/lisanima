-- cre_tbl_m_rulebook_protocol_detail.sql
-- compact/reflect等のワークフロー手順を管理するテーブル
-- rulebookが「何をすべきか（what）」、protocol_detailは「どうやるか（how）」

CREATE TABLE m_rulebook_protocol_detail (
    protocol_name  TEXT NOT NULL,                                          -- 手順名 (例: 'compact', 'reflect')
    seq            INTEGER NOT NULL,                                       -- ステップ番号 (1, 2, 3...)
    content        TEXT NOT NULL,                                          -- ステップ内容（Markdown可）
    exportable     BOOLEAN NOT NULL DEFAULT FALSE,                         -- .claude/rules/ エクスポート対象
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT m_rulebook_protocol_detail_pk PRIMARY KEY (protocol_name, seq)
);
