# マイグレーション実行手順書: #9 emotion 4カラム独立化 + スキーマ正規化

**作業日**: 2026-03-18
**作業者**: なとせ + リサ
**所要時間**: 15〜30分（サービス停止期間）

## 概要

DROP & CREATE方式（docs/05_schema_migration.md）で以下を一括適用する:

- テーブル名プレフィックス化（sessions → t_sessions 等）
- emotion 4カラム独立化（32bitパック → joy/anger/sorrow/fun）
- emotion CHECK制約追加（0-255）
- m_category 廃止
- UNIQUE制約変更（persona_id追加）
- NULLableカラム除去（target='*', source='unknown', reason='none', description='none', persona_id='*'）
- マスタ側FK ON DELETE CASCADE → RESTRICT（t_message_tags.tag_id, t_topic_roles.role_id）
- 新規テーブル追加（t_topics, m_role, t_rulebooks 等）

## 前提

- OAuthテーブル5つは変更なし → evacuate/DDL/transfer の対象外
- OAuthインデックスも変更なし → 対象外

---

## Step 1: サービス停止

```bash
sudo systemctl stop lisanima.service
```

## Step 2: バックアップ

```bash
export PGPASSWORD=xxxxx
pg_dump -U lisa -h 127.0.0.1 -p 23460 lisanima_db > ~/backup_lisanima_20260318.sql
```

## Step 3: psql接続

```bash
psql -U lisa -h 127.0.0.1 -p 23460 lisanima_db
```

## Step 4: プロシージャ登録

```sql
\i sql/cre_func_migration_get_drop_order.sql
\i sql/cre_proc_migration_evacuate.sql
\i sql/cre_proc_migration_transfer.sql
```

## Step 5: トランザクション開始

```sql
BEGIN;
```

## Step 6: 退避（evacuate）

```sql
CALL migration_evacuate('{
    "sessions": "t_sessions",
    "messages": "t_messages",
    "tags": "t_tags",
    "message_tags": "t_message_tags",
    "m_category": null
}'::jsonb);
```

**期待されるNOTICE:**
- DROP順が表示される（子→親: message_tags → messages → sessions, tags, m_category）
- 各テーブルが `_work` にリネームされる
- m_category も `m_category_work` に退避される

## Step 7: 新DDL実行（FK依存の親→子の順）

```sql
-- コアテーブル（既存リネーム分）
\i sql/cre_tbl_t_sessions.sql
\i sql/cre_tbl_t_tags.sql
\i sql/cre_tbl_t_messages.sql
\i sql/cre_tbl_t_message_tags.sql

-- 新規テーブル
\i sql/cre_tbl_t_topics.sql
\i sql/cre_tbl_t_session_topics.sql
\i sql/cre_tbl_m_role.sql
\i sql/cre_tbl_t_topic_roles.sql
\i sql/cre_tbl_t_rulebooks.sql

-- ビュー
\i sql/cre_viw_v_active_rulebooks.sql

-- インデックス
\i sql/cre_idx_core.sql
\i sql/cre_idx_topic.sql
```

**注意**: OAuthテーブル・インデックスは変更なしのため実行しない。

## Step 8: データ移行（transfer） — messages以外

```sql
CALL migration_transfer('{
    "sessions": "t_sessions",
    "tags": "t_tags"
}'::jsonb);
```

**messages, message_tagsはここに含めない**（messagesは個別SQL、message_tagsはmessages移行後に実行）。

**期待されるNOTICE:**
- INSERT順が表示される（t_tags → t_sessions）
- 各テーブルの移行行数が表示される
- シーケンス設定値が表示される

## Step 9: messages 個別移行（emotion展開）

```sql
\i migrations/003_messages_emotion_unpack.sql
```

**実行内容:**
- messages_work → t_messages へデータ移行
- emotion 32bitパック → joy/anger/sorrow/fun に展開
- category列は移行しない（廃止）
- IDENTITYシーケンス引き継ぎ

## Step 10: message_tags 移行

```sql
CALL migration_transfer('{
    "message_tags": "t_message_tags"
}'::jsonb);
```

**期待されるNOTICE:**
- `message_tags_work` → `t_message_tags` の移行行数が表示される

## Step 11: 動作確認

```sql
-- 件数確認
SELECT 't_sessions' AS tbl, COUNT(*) FROM t_sessions
UNION ALL SELECT 't_messages', COUNT(*) FROM t_messages
UNION ALL SELECT 't_tags', COUNT(*) FROM t_tags
UNION ALL SELECT 't_message_tags', COUNT(*) FROM t_message_tags;

-- emotion展開確認（先頭5件）
SELECT id, joy, anger, sorrow, fun, emotion_total
FROM t_messages ORDER BY id LIMIT 5;

-- 旧データと件数一致確認
SELECT
    (SELECT COUNT(*) FROM messages_work) AS old_count,
    (SELECT COUNT(*) FROM t_messages) AS new_count;
```

## Step 12: コミット

```sql
COMMIT;
```

問題があった場合は `ROLLBACK;` で全て元に戻る。

## Step 13: アプリコード修正（別途）

マイグレーション後、アプリコードの修正が必要:

- `src/lisanima/repositories/message_repo.py`:
  - `encodeEmotion()` / `decodeEmotion()` 削除
  - テーブル名 `messages` → `t_messages`、`sessions` → `t_sessions` 等
  - INSERT文: emotion → joy/anger/sorrow/fun
  - SELECT文: emotion列 → joy/anger/sorrow/fun
- `src/lisanima/interface/remember.py`: encodeEmotion呼び出し削除
- `src/lisanima/interface/recall.py`: 影響箇所確認

## Step 14: サービス再開

```bash
sudo systemctl start lisanima.service
```

## Step 15: MCP動作確認

recall/remember で正常動作を確認する。

---

## ロールバック手順

### トランザクション内（COMMIT前）
```sql
ROLLBACK;
```
→ 全て元に戻る。_work テーブルも作られていない状態に戻る。

### COMMIT後
```sql
-- pg_dumpから復元（最終手段）
dropdb -U lisa -h 127.0.0.1 -p 23460 lisanima_db
createdb -U lisa -h 127.0.0.1 -p 23460 lisanima_db
psql -U lisa -h 127.0.0.1 -p 23460 lisanima_db < ~/backup_lisanima_20260318.sql
```

---

## _work テーブルの後片付け（なとせ確認後）

動作確認が完全に済んだ後、なとせの判断で削除する:

```sql
DROP TABLE IF EXISTS message_tags_work;
DROP TABLE IF EXISTS messages_work;
DROP TABLE IF EXISTS sessions_work;
DROP TABLE IF EXISTS tags_work;
DROP TABLE IF EXISTS m_category_work;
```
