# MCPインターフェース仕様: lisanima

## 1. 概要

lisanimaはMCP（Model Context Protocol）サーバーとしてツールを提供する。
**設計方針: MCPコマンド（外部設計）を主役とし、テーブル（内部設計）はコマンドから導出する。**

### トランスポート

| モード | 用途 | 起動方法 |
|--------|------|----------|
| stdio | Claude Code等ローカルLLMクライアント | `lisanima`（デフォルト） |
| Streamable HTTP | リモートクライアント（Desktop App等） | `lisanima --http [--port 8765]` |

- stdioモード: LLMクライアントがサブプロセスとして起動。認証不要
- HTTPモード: `127.0.0.1` にバインド。nginx SSL終端経由でリモートアクセス

### 認証

HTTPモードはMCP仕様に準拠した **OAuth 2.1** 認証を実装する。詳細は [07_oauth.md](07_oauth.md) を参照。

- 外部URL: `https://<your-domain>/lisanima/mcp`
- nginx SSL終端 → `http://127.0.0.1:8765/` にプロキシ

### フェーズ境界

| フェーズ | 範囲 | 判断基準 |
|----------|------|----------|
| Ph1.0 | 記録/整理/参照 | emotionを「記録する」 |
| Ph2.0 | 情報の加工 | emotionを「利用する」 |

- **Ph1.0**: remember, forget, recall, rulebook, topic_manage, organize
- **Ph2.0**: compact, reflect, 能動的発話, メンタル管理

## 2. コマンド一覧

| コマンド | 概要 | Phase | 状態 |
|----------|------|-------|------|
| remember | 記憶を保存する | Ph1.0 | 改修（category廃止、topic_id追加） |
| forget | 記憶を論理削除する | Ph1.0 | 新実装 |
| recall | 記憶を検索する | Ph1.0 | 改修（category廃止、topic_idフィルタ追加） |
| rulebook | ルール参照・管理 | Ph1.0 | 新実装 |
| topic_manage | トピックCRUD | Ph1.0 | 新実装 |
| organize | タグ整理 | Ph1.0 | 新実装 |

## 3. コマンド詳細

### 3.1 remember -- 記憶を保存

セッション中の発言・知見をDBに保存する。

**入力パラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| content | string | Yes | 発言・記憶の内容 |
| speaker | string | Yes | 発言者名（例: リサ / なとせ / ありす / 桃華 / ほたる / 晶葉。制約なし、任意の文字列を受け付ける） |
| target | string | No | 発言先（デフォルト: null） |
| emotion | object | No | 感情値。省略時は全感情値0として扱われる（{joy:0, anger:0, sorrow:0, fun:0} と等価） |
| topic_id | integer | No | トピックID。指定時はセッションとトピックの紐付けも自動作成 |
| project | string | No | 発言の文脈（例: "lisanima", "crypto_trade_bot", "Desktop"） |
| session_date | string | No | セッション日付 YYYY-MM-DD（デフォルト: 今日）。過去・未来いずれも受け付ける |

**改修点（旧仕様からの変更）:**
- `category` 引数を廃止（分類はタグで吸収）
- `tags` 引数を廃止（タグ付けはorganizeに委譲）
- `topic_id` 引数を追加（任意。指定時はセッションとトピックの紐付けも自動作成）

**emotion オブジェクト:**

| フィールド | 型 | 範囲 | 説明 |
|-----------|-----|------|------|
| joy | integer | 0-255 | 喜び |
| anger | integer | 0-255 | 怒り |
| sorrow | integer | 0-255 | 哀しみ |
| fun | integer | 0-255 | 楽しさ |

**処理フロー:**
1. 該当日付のセッションを検索（なければ新規作成）
2. emotion を保存
3. topic_id 指定時はセッションとトピックの紐付けも自動作成
4. メッセージを保存し、IDを返却

**レスポンス:**

| フィールド | 型 | 説明 |
|-----------|-----|------|
| message_id | integer | 作成されたメッセージID |
| session_id | integer | 所属セッションID |
| status | string | "saved" |

```json
{
  "message_id": 42,
  "session_id": 5,
  "status": "saved"
}
```

### 3.2 forget -- 記憶を論理削除

指定した記憶を論理削除する。物理削除は行わない。

**入力パラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| message_id | integer | Yes | 削除対象のメッセージID |
| reason | string | No | 削除理由 |

**処理フロー:**
1. 対象メッセージを論理削除する（存在しない場合は NOT_FOUND エラー）
2. reason が指定されていれば削除理由を記録
3. recall の検索結果からは除外される

**レスポンス:**

| フィールド | 型 | 説明 |
|-----------|-----|------|
| message_id | integer | 削除されたメッセージID |
| status | string | "forgotten" |

```json
{
  "message_id": 42,
  "status": "forgotten"
}
```

### 3.3 recall -- 記憶を検索

過去の記憶をキーワード・タグ・日付・感情値で検索する。

**入力パラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| query | string[] | No | 全文検索キーワード（AND検索） |
| tags | string[] | No | タグ名でフィルタ（AND検索） |
| speaker | string | No | 発言者でフィルタ |
| project | string | No | プロジェクト名でフィルタ |
| topic_id | integer[] | No | トピックIDでフィルタ（OR検索。未指定時は横断） |
| date_from | string | No | 日付範囲の開始（YYYY-MM-DD） |
| date_to | string | No | 日付範囲の終了（YYYY-MM-DD） |
| emotion_filter | object | No | 感情値のレンジフィルタ（後述） |
| limit | integer | No | 取得件数上限（デフォルト: 20） |
| offset | integer | No | オフセット（デフォルト: 0） |

**emotion_filter オブジェクト:**

各感情軸に対して `min` / `max` でレンジ指定する。複数軸指定時は AND（全条件一致）。省略した軸は条件なし。

```json
{
  "joy": {"min": 10, "max": 255},
  "anger": {"min": 150},
  "sorrow": {"max": 50},
  "fun": {}
}
```

| パターン | 意味 |
|---------|------|
| `{"min": 10, "max": 255}` | 10〜255の範囲を抽出 |
| `{"min": 150}` | 150以上を抽出 |
| `{"max": 50}` | 50以下を抽出 |
| `{}` またはキー省略 | 条件なし |

**改修点（旧仕様からの変更）:**
- `category` 引数を廃止
- `topic_id` フィルタを追加
- `project` フィルタを追加
- `min_emotion` を廃止し、`emotion_filter`（レンジ検索）に置き換え

**全パラメータ省略時のデフォルト動作:**
- フィルタ条件なしで最新20件を返却（新しい順）
- 論理削除済みメッセージは常に除外

**検索優先度:**
1. 全文検索スコア（類似度） ※query指定時
2. 感情値合計（高い方が優先）
3. 作成日時（新しい方が優先）

**レスポンス:**

| フィールド | 型 | 説明 |
|-----------|-----|------|
| total | integer | 検索結果の総件数 |
| messages | array | メッセージオブジェクトの配列 |

```json
{
  "total": 3,
  "messages": [
    {
      "id": 42,
      "session_date": "2026-03-07",
      "speaker": "リサ",
      "target": null,
      "content": "pg_trgmは日本語トライグラム検索に対応している",
      "emotion": {"joy": 0, "anger": 0, "sorrow": 0, "fun": 128},
      "emotion_total": 128,
      "source": "Claude Code",
      "project": "lisanima",
      "tags": ["postgresql", "全文検索"],
      "created_at": "2026-03-07T14:30:00+09:00"
    }
  ]
}
```

### 3.4 rulebook -- ルール参照・管理

ルールブックの参照・設定・廃止を行う。イミュータブル追記型で、バージョン管理される。
最新かつ有効なルールのみを取得する。

**入力パラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| action | string | Yes | "get" / "set" / "retire" / "list" |
| key | string | get/set/retire時必須 | ルールキー（例: "persona.tone", "format.code_review"） |
| content | string | set時必須 | ルール本文（Markdown） |
| reason | string | No | 変更理由 |
| persona_id | string | No | ペルソナID（NULLなら全ペルソナ共通ルール） |

**action別の動作:**

| action | 動作 | 必須パラメータ |
|--------|------|---------------|
| get | 指定keyの最新有効ルールを取得 | key |
| set | 新バージョンのルールを追記（既存keyならversion+1） | key, content |
| retire | 指定keyの最新版を廃止にする。廃止後も同keyで再setすると次バージョンで復活 | key |
| list | 有効なルール一覧を取得（persona_idでフィルタ可） | なし |

**レスポンス（get）:**
```json
{
  "key": "persona.tone",
  "content": "生意気なメスガキ口調。簡潔に要点を先に述べる。",
  "version": 3,
  "persona_id": "lisa",
  "created_at": "2026-03-12T10:00:00+09:00"
}
```

**レスポンス（list）:**
```json
{
  "rules": [
    {
      "key": "persona.tone",
      "content": "...",
      "version": 3,
      "persona_id": "lisa"
    },
    {
      "key": "format.code_review",
      "content": "...",
      "version": 1,
      "persona_id": null
    }
  ]
}
```

### 3.5 topic_manage -- トピックCRUD

トピック（議題）の作成・クローズ・再開・更新を行う。

**入力パラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| action | string | Yes | "create" / "close" / "reopen" / "update" |
| topic_id | integer | close/reopen/update時必須 | トピックID |
| name | string | create時必須 | トピック名（UNIQUEにしない。同名でも別インスタンス） |
| roles | string[] | No | 役割名の配列（後述の代表例を参照） |
| emotion | object | No | リサの主観的感情値 |
| session_id | integer | No | セッションIDとの紐付け |

**roles 代表例:**

| role | 説明 | 例 |
|------|------|-----|
| sparring | 壁打ち | 存在論、設計思想 |
| support | QA・技術サポート | エラー対応、使い方 |
| review | レビュー | コード、設計、文章 |
| study | 学習・調査 | 新技術、論文読み |
| casual | 雑談 | 世間話、近況 |
| coaching | 進捗管理・リマインド | Note執筆の件 |
| writing | 文章作成・編集 | ドキュメント、ブログ、メール |
| analysis | 分析・調査レポート | データ分析、比較調査 |
| planning | 計画立案 | ロードマップ、スケジュール |
| creative | 創作 | ネーミング、アイデア出し |
| facilitation | 議論整理・ファシリテーション | 多人数議論のまとめ |

※ 上記は代表例。任意の文字列を登録可能。マスタ管理の詳細は [04_schema.md](04_schema.md) を参照。

**action別の動作:**

| action | 動作 | 必須パラメータ |
|--------|------|---------------|
| create | トピックを作成。roles指定時は役割も紐付け | name |
| close | トピックをクローズする | topic_id |
| reopen | トピックを再開する | topic_id |
| update | 指定フィールドのみ部分更新（未指定フィールドは既存値を保持） | topic_id |

**レスポンス（create）:**
```json
{
  "topic_id": 7,
  "name": "OAuth 2.1認証実装",
  "status": "open",
  "roles": ["review", "study"]
}
```

### 3.6 organize -- タグ整理

メッセージへのタグ付け・タグ外しを行う。rememberからタグ付け責務を分離した専用コマンド。
検索条件ベースで対象を指定でき、特定期間・プロジェクト・トピック単位での横断整理が可能。

**入力パラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| message_ids | integer[] | No | 対象メッセージIDの直接指定（検索条件との併用可） |
| query | string[] | No | 全文検索キーワード（AND検索） |
| tags | string[] | No | 既存タグでフィルタ（AND検索） |
| speaker | string | No | 発言者でフィルタ |
| project | string | No | プロジェクト名でフィルタ |
| topic_id | integer[] | No | トピックIDでフィルタ（OR検索。未指定時は横断） |
| date_from | string | No | 日付範囲の開始（YYYY-MM-DD） |
| date_to | string | No | 日付範囲の終了（YYYY-MM-DD） |
| emotion_filter | object | No | 感情値のレンジフィルタ（recall と同仕様） |
| include_deleted | boolean | No | 論理削除済みも対象にする（デフォルト: false） |
| add_tags | string[] | No | 追加するタグ名の配列（未登録タグは自動作成。lower + trimで正規化） |
| remove_tags | string[] | No | 削除するタグ名の配列 |
| limit | integer | No | 処理件数上限（デフォルト: 100000） |

**recallとの違い:**

recallは「記憶を読む」ためのコマンド、organizeは「記憶を整理する」ためのコマンド。
検索条件は共通だが、目的と制約が異なる。

| 観点 | recall | organize |
|------|--------|----------|
| 目的 | 記憶の参照 | タグの横断整理 |
| 論理削除済み | 常に除外 | `include_deleted: true` で対象可 |
| limit デフォルト | 20 | 100000 |

**処理フロー:**
1. 検索条件またはmessage_idsで対象メッセージを特定
2. add_tags: 未登録タグは自動作成し、メッセージに紐付け
3. remove_tags: メッセージからタグの紐付けを削除（タグ自体は残す）

**注意事項:**
- add_tags と remove_tags に同一タグを指定した場合は INVALID_PARAMETER エラー

**レスポンス:**

| フィールド | 型 | 説明 |
|-----------|-----|------|
| organized_count | integer | 処理されたメッセージ数 |
| tags_added | string[] | 追加されたタグ名 |
| tags_removed | string[] | 削除されたタグ名 |

```json
{
  "organized_count": 3,
  "tags_added": ["postgresql", "全文検索"],
  "tags_removed": ["wip"]
}
```

## 4. コマンドから導出されたテーブル一覧

外部設計（MCPコマンド）から、各コマンドが必要とするテーブルを導出した結果。

| テーブル | 種別 | 参照コマンド | 状態 |
|----------|------|-------------|------|
| t_sessions | コア | remember, recall | 改修（UNIQUE制約変更） |
| t_messages | コア | remember, forget, recall, organize | 改修（category列削除） |
| t_tags | コア | recall, organize | 変更なし |
| t_message_tags | コア | recall, organize | 変更なし |
| t_topics | 新設 | remember, recall, topic_manage | 新規 |
| t_session_topics | 新設 | remember, recall, topic_manage | 新規 |
| m_role | 新設 | topic_manage | 新規 |
| t_topic_roles | 新設 | topic_manage | 新規 |
| m_rulebooks | 新設 | rulebook | 新規 |
| v_active_rulebooks | 新設（ビュー） | rulebook | 新規 |
| m_category | 廃止 | - | **どのコマンドからも参照されないことが外部設計から証明** |

テーブルの詳細定義は [04_schema.md](04_schema.md) を参照。

## 5. エラーハンドリング

全コマンド共通のエラーレスポンス形式:

```json
{
  "error": "ERROR_CODE",
  "message": "人間が読めるエラーメッセージ"
}
```

| エラーコード | 意味 |
|-------------|------|
| DB_CONNECTION_ERROR | DB接続失敗 |
| INVALID_PARAMETER | パラメータ不正 |
| NOT_FOUND | 対象が見つからない |
| INTERNAL_ERROR | 予期しないエラー |

## 6. MCP サーバー実装

実装は `src/lisanima/server.py` を参照。

- 各コマンドは `@mcp.tool()` デコレータで登録
- 処理本体は `src/lisanima/tools/` 配下に委譲
- HTTPモード時は OAuth 2.1 認証と `/auth/pin` カスタムルートが追加される
