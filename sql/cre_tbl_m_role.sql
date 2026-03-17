-- cre_tbl_m_role.sql
-- m_role テーブル定義 + 初期データ

CREATE TABLE m_role (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT 'none',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO m_role (name, description) VALUES
    ('sparring',      '議論の壁打ち相手'),
    ('support',       'サポート・補助'),
    ('review',        'レビュー・品質確認'),
    ('study',         '学習・研究'),
    ('casual',        '雑談・日常会話'),
    ('coaching',      '指導・コーチング'),
    ('writing',       '文章作成・編集'),
    ('analysis',      '分析・調査レポート'),
    ('planning',      '計画立案'),
    ('creative',      '創作'),
    ('facilitation',  '議論整理・ファシリテーション');
