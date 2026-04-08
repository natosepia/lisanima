-- 004_messages_compacted_from.sql
-- t_messages に compacted_from INTEGER[] 列を追加
-- 用途: compact 手順で複数メッセージを1件に統合した際、元のid群をトレースする
-- 関連: issue #47 compact/reflect 手順確立

BEGIN;

ALTER TABLE t_messages
    ADD COLUMN IF NOT EXISTS compacted_from INTEGER[];

-- 逆引きで「この記憶の圧縮元は？」「idXを統合したメッセージは？」を辿れるようにする
CREATE INDEX IF NOT EXISTS ix_t_messages_compacted_from
    ON t_messages USING GIN (compacted_from);

COMMIT;
