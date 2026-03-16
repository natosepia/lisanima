-- ============================================================
-- 003_messages_emotion_unpack.sql
-- messages テーブル個別マイグレーション: emotion 32bitパック → 4カラム分離
-- ============================================================
--
-- 概要:
--   messages_work（旧 messages）から t_messages へデータを移行する。
--   emotion INTEGER（32bitパック）を joy/anger/sorrow/fun の4カラムに展開する。
--   category列は廃止のため移行しない。
--
-- 前提条件:
--   1. migration_evacuate() 実行済み（messages → messages_work にリネーム済み）
--   2. t_messages の新DDL（04_schema.md セクション7）が CREATE 済み
--   3. t_sessions のデータ移行が完了済み（FK参照先）
--   4. BEGIN/COMMIT は呼び出し側で制御する（本SQL内には含まない）
--
-- emotion ビットレイアウト（旧仕様）:
--   bits 31-24: joy
--   bits 23-16: anger
--   bits 15-8:  sorrow
--   bits 7-0:   fun
--
-- 除外カラム:
--   - category: m_category 廃止に伴い移行しない（タグで吸収）
--   - emotion: 4カラムに展開して移行
--   - emotion_total: Generated Column（自動計算されるため移行不要）
-- ============================================================


-- ------------------------------------------------------------
-- 1. データ移行: messages_work → t_messages
-- ------------------------------------------------------------
INSERT INTO t_messages (
    id,
    session_id,
    speaker,
    target,
    content,
    joy,
    anger,
    sorrow,
    fun,
    -- emotion_total は Generated Column のため指定しない
    source,
    is_deleted,
    deleted_reason,
    created_at
)
OVERRIDING SYSTEM VALUE
SELECT
    id,
    session_id,
    speaker,
    target,
    content,
    ((emotion >> 24) & 255)::smallint AS joy,
    ((emotion >> 16) & 255)::smallint AS anger,
    ((emotion >>  8) & 255)::smallint AS sorrow,
    (emotion         & 255)::smallint AS fun,
    source,
    is_deleted,
    deleted_reason,
    created_at
FROM messages_work;


-- ------------------------------------------------------------
-- 2. IDENTITY シーケンスの引き継ぎ
-- ------------------------------------------------------------
-- t_messages.id の IDENTITY シーケンスを既存データの最大値に合わせる
SELECT setval(
    pg_get_serial_sequence('t_messages', 'id'),
    COALESCE((SELECT MAX(id) FROM t_messages), 0),
    COALESCE((SELECT MAX(id) FROM t_messages), 0) > 0
);


-- ------------------------------------------------------------
-- 3. 確認用クエリ（参考: コメントアウト）
-- ------------------------------------------------------------

-- 移行件数の比較
-- SELECT
--     (SELECT COUNT(*) FROM messages_work)  AS work_count,
--     (SELECT COUNT(*) FROM t_messages)     AS new_count;

-- emotion展開結果のサンプル確認（先頭5件）
-- SELECT
--     w.id,
--     w.emotion                              AS old_emotion,
--     m.joy, m.anger, m.sorrow, m.fun,
--     m.emotion_total
-- FROM messages_work w
-- JOIN t_messages m ON m.id = w.id
-- ORDER BY w.id
-- LIMIT 5;

-- emotion再パック検算: 展開→再パック結果が元のemotionと一致するか
-- SELECT
--     w.id,
--     w.emotion AS original,
--     (m.joy::int << 24) | (m.anger::int << 16) | (m.sorrow::int << 8) | m.fun::int AS repacked,
--     w.emotion = ((m.joy::int << 24) | (m.anger::int << 16) | (m.sorrow::int << 8) | m.fun::int) AS match
-- FROM messages_work w
-- JOIN t_messages m ON m.id = w.id
-- WHERE w.emotion <> ((m.joy::int << 24) | (m.anger::int << 16) | (m.sorrow::int << 8) | m.fun::int);
-- 結果が0件なら全行一致
