# lisanima プロジェクト固有ルール

## Issue管理

- バックログ・タスク・バグは GitHub Issue で管理する
- テンプレート: `.github/ISSUE_TEMPLATE/` 配下（bug_report / feature_request）
- issueは日本語で記載する

### ラベル運用

| ラベル | 用途 |
|--------|------|
| `bug` | バグ報告 |
| `enhancement` | 機能要望・改善 |
| `ph1.5` | Phase 1.5: 整理・リファクタ |
| `ph2` | Phase 2: 情報の加工・CLI |
| `ph3` | Phase 3+: ベクトル検索・Web UI等 |

### issue起票

- テンプレート: `.github/ISSUE_TEMPLATE/` を参照して起票する
- `gh issue create` で作成、ラベルは必ず付与する
- **起票者明記**: GitHubアカウントが共通（natosepia）のため、bodyの先頭に `起票者: リサ` 等を記載する

### エージェントのissue操作

- ありす・桃華・ほたる・晶葉は `gh` CLIでissueを参照・更新できる
- 作業開始時: `gh issue view <番号>` で内容確認
- 作業完了時: issueにコメントを残す（`gh issue comment <番号> --body "..."`)

## Discussion管理

- 設計思想・技術知見・ビジョンなど「答えが出なくてもいい議論」は GitHub Discussions で管理する
- 結論が出てタスク化する場合は issue に昇格する
- **発言者明記**: 投稿・コメント時に `発言者: ありす` 等を記載する（GitHubアカウント共通のため）

### カテゴリ運用

| カテゴリ | 用途 |
|---------|------|
| Ideas | ビジョン・思想・設計コンセプトの議論 |
| ComputerScienceTech | TCP/IP、OAuth、アルゴリズム等の技術知見 |
| General | 雑多な議論・相談 |
| Q&A | 技術的な質問 |
