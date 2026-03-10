# TICKET-001: docs レビュー指摘対応

| 項目 | 内容 |
|------|------|
| 起票日 | 2026-03-08 |
| 起票者 | ありす（レビュー） |
| 担当者 | リサ |
| ステータス | Closed |
| 完了日 | 2026-03-08 |
| 種別 | ドキュメント修正 |

## 背景

ありす（バックエンドエンジニア）による docs/ 全5ファイルのレビュー結果に基づく修正。

---

## 修正タスク

### [A] 要修正（Must Fix）

| # | 対象ファイル | 内容 | 状態 |
|---|-------------|------|------|
| A-1 | 02_architecture.md | 構成図の `messages_fts` をテーブルではなくGINインデックスとして正しく記載 | [x] |
| A-2 | 03_schema.md | emotion列の符号付き32bit問題を明記。符号付き挙動の注意書き追加 | [x] |
| A-3 | 03_schema.md | speaker列にCHECK制約を付けない理由を明記（Phase 3マルチユーザー拡張を考慮） | [x] |
| A-4 | 04_mcp-tools.md | rememberのセッション自動作成ルールを明確化（同日の最新セッションに追加） | [x] |
| A-5 | 04_mcp-tools.md | forgetのreason保存先を決定（deleted_reasonカラムをDBに追加） | [x] |
| A-6 | 04_mcp-tools.md | recallのmin_emotion問題に対応（emotion_total Generated Column追加） | [x] |
| A-7 | 01 × 04 横断 | Phase分割の矛盾を解消（emotionをPhase 1に繰り上げ） | [x] |

### [B] 改善提案（Should Fix）

| # | 対象ファイル | 内容 | 状態 |
|---|-------------|------|------|
| B-1 | 03_schema.md | tags.nameの正規化ルール追記（lower + trim） | [x] |
| B-2 | 03_schema.md | sessions.ended_atの更新タイミング明記 | [x] |
| B-3 | 03_schema.md | SERIAL → IDENTITY 推奨への変更 | [x] |
| B-4 | 03_schema.md | ON DELETE CASCADEのリスク認識を明記 | [x] |
| B-5 | 04_mcp-tools.md | recallの全パラメータ省略時のデフォルト動作明記 | [x] |
| B-6 | 04_mcp-tools.md | reflectのレスポンスにspeaker追加 | [x] |
| B-7 | 04_mcp-tools.md | recallのdate_from/date_toがsessions.dateに対して適用されることを明記 | [x] |
| B-8 | 01_requirements.md | 非機能要件にバックアップ/リカバリ追記 | [x] |
| B-9 | 05_migration.md | パース仕様を実際のMarkdownフォーマットに合わせて精緻化（概要レベル + 実装時に確定） | [x] |

---

## 対応方針

- A（要修正）は全件対応
- B（改善提案）も全件対応（コスト低いため）
- B-9（移行パース仕様の精緻化）は概要レベルの記載に留め、実装時に詳細化
