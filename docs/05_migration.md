# Markdown → DB移行計画: lisanima

## 1. 概要

既存の `~/claude_communication_log/`（絶対パス: `/home/natosepia/claude_communication_log/`）配下のMarkdownファイルをパースし、lisanima DBに移行する。

## 2. 移行対象

### ソース
```
~/claude_communication_log/
├── YYYY-MM-DD_session.md
├── YYYY-MM-DD_backlog.md
├── YYYY-MM-DD_knowledge.md
└── YYYY-MM-DD_discussion.md
```

### ファイル名 → テーブルマッピング

| ファイル名パターン | category値 |
|-------------------|-----------|
| `*_session.md` | session |
| `*_backlog.md` | backlog |
| `*_knowledge.md` | knowledge |
| `*_discussion.md` | discussion |
| `*_report.md` | report |

## 3. パース仕様

### 3.1 session.md のパースルール

```markdown
# 会話ログ: YYYY-MM-DD

## トピック名（オプション）

**発言者名**: 発言内容

**リサ**: 応答内容

---

## 別トピック（セッション区切り後）
```

- `# 会話ログ: YYYY-MM-DD` → sessions.date
- `**発言者名**: 内容` → messages.speaker, messages.content
- `---` → セッション区切り（同日内のsession_seqをインクリメント）
- `## 見出し` → トピック名として、直後の発言群のcontextに含める（見出し自体は独立メッセージにしない）
- 複数行にわたる発言（次の `**発言者名**:` が出現するまで）は1つのcontentとして結合

### 3.2 backlog / knowledge / discussion のパースルール

- `## タイトル` ごとに1メッセージとして保存
- セクション内の本文全体を content に格納（コードブロック含む。長文になることを許容）
- `###` 以下の小見出しは親の `##` のcontentに含める（分割しない）
- speaker はデフォルト「リサ」（記録者がリサのため）
- 明示的に `**なとせ**:` 等の発言パターンが含まれる場合はspeakerを切り替える

### 3.3 パース上の注意点

- コードブロック（` ``` `）内の `**太字**` はパース対象外（コードブロック内はそのまま保持）
- 発言者名に該当しないパターン（見出し、リスト等）はコンテキストとして直前の発言に結合
- 空行は無視、区切り線（`---`）はセッション区切りとして処理
- パースエラー発生時は**エラー行をスキップして継続**（ファイル全体はスキップしない）
- エラー箇所はレポートに行番号付きで記録

### 3.4 パース仕様の限界

本パース仕様はPhase 1時点での概要設計。実装時に既存Markdownの実態を網羅的に検証し、必要に応じて仕様を更新する。
特に以下は実装時に確定させる：
- セッション区切りが `---` 以外のパターン（`## Session 2` 等）で表現されているケース
- backlog.mdに含まれるなとせの判断・調査結果のspeaker判定ルール

## 4. 移行フロー

```
1. ~/claude_communication_log/ のファイル一覧を取得
2. ファイル名から日付・カテゴリを抽出
3. 日付ごとに sessions レコードを作成
4. Markdownをパースして messages レコードを生成
5. バルクINSERT（トランザクション単位: 1ファイル）
6. 移行結果レポートを出力
```

## 5. 移行スクリプト

### 実行方法
```bash
uv run python scripts/migrate_markdown.py
```

### オプション
| オプション | 説明 |
|-----------|------|
| `--source` | ソースディレクトリ（デフォルト: `~/claude_communication_log/`） |
| `--dry-run` | DBに書き込まず、パース結果だけ表示 |
| `--date` | 特定日付のみ移行（YYYY-MM-DD） |
| `--force` | 該当日付のsessions・messagesをDELETEしてからINSERT（部分上書き） |

### 出力レポート例
```
Migration Report:
  Files processed: 45
  Sessions created: 38
  Messages created: 1,204
  Tags created: 0 (auto-tagging is Phase 2)
  Errors: 2
    - 2026-02-15_session.md: Parse error at line 42
    - 2026-02-20_session.md: Empty file skipped
```

## 6. データ整合性チェック

移行後に実行するバリデーション:

```sql
-- 1. sessionsの日付に対応するファイルが存在するか
-- 2. messagesの件数がMarkdownの発言数と一致するか
-- 3. 孤立したmessages（session_idが無効）がないか
SELECT m.id FROM messages m
LEFT JOIN sessions s ON m.session_id = s.id
WHERE s.id IS NULL;
```

## 7. ロールバック

移行をやり直す場合:

```sql
-- 全データ削除（移行データのみ。手動追加分がない前提）
TRUNCATE message_tags, messages, sessions, tags RESTART IDENTITY CASCADE;
```

## 8. 移行後の運用切り替え

移行完了後の運用方針:

| 項目 | 移行前 | 移行後 |
|------|--------|--------|
| 記憶の保存先 | Markdownファイル | lisanima DB（MCPツール経由） |
| 記憶の検索 | grep / ファイル読み込み | recall ツール |
| Markdownファイル | 新規作成を継続 | 読み取り専用アーカイブとして保持 |
| MEMORY.md | 手動管理 | reflect ツールで自動整理（Phase 2） |

**注意:** 移行後もMarkdownファイルは削除しない。バックアップとして保持する。
