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

HTTPモードはMCP仕様に準拠した **OAuth 2.1** 認証を実装する。詳細は [06_oauth.md](06_oauth.md) を参照。

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
| topic_id | integer | No | トピックID。指定時はt_session_topicsも自動作成 |
| project | string | No | プロジェクト名（デフォルト: null） |
| session_date | string | No | セッション日付 YYYY-MM-DD（デフォルト: 今日） |

**改修点（旧仕様からの変更）:**
- `category` 引数を廃止（m_category廃止に伴い、分類はタグで吸収）
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
1. 該当日付のセッションを検索
   - 存在しない → 新規セッションを作成（session_seq = 1）
   - 存在する → 同日の最新セッション（session_seq が最大のもの）に追加
2. emotion オブジェクトを4バイト整数にエンコード
3. topic_id が指定されていれば、t_session_topics に紐付けを作成（ON CONFLICT DO NOTHING）
4. t_messages テーブルにINSERT
5. 保存したメッセージIDを返却

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

指定した記憶を論理削除する（is_deleted = TRUE）。物理削除は行わない。

**入力パラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| message_id | integer | Yes | 削除対象のメッセージID |
| reason | string | No | 削除理由（t_messages.deleted_reason に保存） |

**処理フロー:**
1. 対象メッセージの is_deleted を TRUE に更新
2. reason が指定されていれば deleted_reason カラムに保存
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
| query | string | No | 全文検索キーワード（pg_trgm） |
| tags | string[] | No | タグ名でフィルタ（AND検索） |
| speaker | string | No | 発言者でフィルタ |
| topic_id | integer | No | トピックIDでフィルタ（t_session_topics経由） |
| date_from | string | No | 日付範囲の開始（YYYY-MM-DD）。t_sessions.date に対して適用 |
| date_to | string | No | 日付範囲の終了（YYYY-MM-DD）。t_sessions.date に対して適用 |
| min_emotion | integer | No | emotion_total（感情値合計）が指定値以上の記憶を抽出 |
| limit | integer | No | 取得件数上限（デフォルト: 20） |
| offset | integer | No | オフセット（デフォルト: 0） |

**改修点（旧仕様からの変更）:**
- `category` 引数を廃止
- `topic_id` フィルタを追加（セッション→セッショントピック→トピック経由でフィルタ）

**全パラメータ省略時のデフォルト動作:**
- フィルタ条件なしで最新20件を返却（created_at降順）
- is_deleted = TRUE のメッセージは常に除外

**検索優先度:**
1. 全文検索スコア（pg_trgm類似度） ※query指定時
2. emotion_total（高い方が優先）
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
      "tags": ["postgresql", "全文検索"],
      "created_at": "2026-03-07T14:30:00+09:00"
    }
  ]
}
```

### 3.4 rulebook -- ルール参照・管理

ルールブックの参照・設定・廃止を行う。イミュータブル追記型で、バージョン管理される。
v_active_rulebooks ビュー経由で最新かつ有効なルールのみを取得する。

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
| retire | 指定keyの最新版をis_retired=TRUEに | key |
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
| roles | string[] | No | 役割名の配列（m_roleのnameを指定） |
| emotion | integer | No | リサの主観的感情値（4バイトベクトル） |
| session_id | integer | No | セッションIDとの紐付け（t_session_topics） |

**action別の動作:**

| action | 動作 | 必須パラメータ |
|--------|------|---------------|
| create | トピックを作成。roles指定時はt_topic_rolesも作成 | name |
| close | トピックのstatusを'closed'に、closed_atを設定 | topic_id |
| reopen | トピックのstatusを'open'に、closed_atをNULLに | topic_id |
| update | name, roles, emotionなどを更新 | topic_id |

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

**入力パラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| message_ids | integer[] | Yes | 対象メッセージIDの配列 |
| add_tags | string[] | No | 追加するタグ名の配列（未登録タグは自動作成。lower + trimで正規化） |
| remove_tags | string[] | No | 削除するタグ名の配列 |

**処理フロー:**
1. add_tags: 未登録タグを自動作成し、message_tagsに紐付けを追加
2. remove_tags: message_tagsから紐付けを削除（タグ自体は残す）

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
| t_rulebooks | 新設 | rulebook | 新規 |
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

## 6. MCP サーバー定義

```python
from mcp.server.fastmcp import FastMCP

# HTTPモード時はOAuth 2.1認証を有効にしてインスタンス生成
mcp = _createMcp()

@mcp.tool()
async def remember(content: str, speaker: str, ...) -> dict:
    """記憶を保存する"""
    return await remember_impl(...)

@mcp.tool()
async def forget(message_id: int, ...) -> dict:
    """記憶を論理削除する"""
    return await forget_impl(...)

@mcp.tool()
async def recall(query: str = None, ...) -> dict:
    """記憶を検索する"""
    return await recall_impl(...)

@mcp.tool()
async def rulebook(action: str, ...) -> dict:
    """ルール参照・管理"""
    return await rulebook_impl(...)

@mcp.tool()
async def topic_manage(action: str, ...) -> dict:
    """トピックCRUD"""
    return await topic_manage_impl(...)

@mcp.tool()
async def organize(message_ids: list[int], ...) -> dict:
    """タグ整理"""
    return await organize_impl(...)
```

HTTPモード時は `/auth/pin` カスタムルートも追加される:

```python
@mcp.custom_route("/auth/pin", methods=["GET", "POST"])
async def pin_handler(request: Request) -> Response:
    ...
```
