# MCPツール仕様: lisanima

## 1. 概要

lisanimaはMCP（Model Context Protocol）サーバーとしてツールを提供する。
Phase 1では2つ（remember, recall）を実装済み、Phase 2で2つ（forget, reflect）を追加予定。

### トランスポート

| モード | 用途 | 起動方法 |
|--------|------|----------|
| stdio | Claude Code等ローカルLLMクライアント | `lisanima`（デフォルト） |
| Streamable HTTP | リモートクライアント（Desktop App等） | `lisanima --http [--port 8765]` |

- stdioモード: LLMクライアントがサブプロセスとして起動。認証不要
- HTTPモード: `127.0.0.1` にバインド。nginx SSL終端経由でリモートアクセス

### 認証

HTTPモードはMCP仕様に準拠した **OAuth 2.1** 認証を実装する。詳細は [06_oauth.md](06_oauth.md) を参照。

- 外部URL: `https://quriowork.com/lisanima/mcp`
- nginx SSL終端 → `http://127.0.0.1:8765/` にプロキシ

## 2. ツール一覧

| ツール | 概要 | Phase |
|--------|------|-------|
| remember | 記憶を保存する | Phase 1 |
| recall | 記憶を検索する | Phase 1 |
| forget | 記憶を論理削除する | Phase 2 |
| reflect | 感情値の高い記憶を振り返る | Phase 2 |

## 3. ツール詳細

### 3.1 remember — 記憶を保存

セッション中の発言・知見をDBに保存する。

**入力パラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| content | string | Yes | 発言・記憶の内容 |
| speaker | string | Yes | 発言者名（例: リサ / なとせ / ありす / 桃華 / ほたる / 晶葉。制約なし、任意の文字列を受け付ける） |
| category | string | No | 種別（デフォルト: "session"）。session / backlog / knowledge / discussion / report |
| target | string | No | 発言先（デフォルト: null） |
| emotion | object | No | 感情値。省略時は全感情値0として扱われる（{joy:0, anger:0, sorrow:0, fun:0} と等価）。実装上はNullableで、未指定時に内部で全0にフォールバック |
| tags | string[] | No | タグ名の配列（デフォルト: []） |
| project | string | No | プロジェクト名（デフォルト: null） |
| session_date | string | No | セッション日付 YYYY-MM-DD（デフォルト: 今日） |

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
   - 存在する → **同日の最新セッション（session_seq が最大のもの）に追加**
   - session_date に過去日付が指定された場合も同じルール（移行スクリプト以外での使用は非推奨）
2. emotion オブジェクトを4バイト整数にエンコード
3. tags が指定されていれば、未登録タグは自動作成（lower + trim で正規化）し紐付け
4. messages テーブルにINSERT
5. 保存したメッセージIDを返却

**レスポンス例:**
```json
{
  "message_id": 42,
  "session_id": 5,
  "tags_created": ["新規タグ"],
  "status": "saved"
}
```

### 3.2 recall — 記憶を検索

過去の記憶をキーワード・タグ・日付・感情値で検索する。

**入力パラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| query | string | No | 全文検索キーワード（pg_trgm） |
| tags | string[] | No | タグ名でフィルタ（AND検索） |
| speaker | string | No | 発言者でフィルタ |
| category | string | No | 種別でフィルタ |
| date_from | string | No | 日付範囲の開始（YYYY-MM-DD）。sessions.date に対して適用 |
| date_to | string | No | 日付範囲の終了（YYYY-MM-DD）。sessions.date に対して適用 |
| min_emotion | integer | No | emotion_total（感情値合計）が指定値以上の記憶を抽出。Generated Columnのインデックスを使用 |
| limit | integer | No | 取得件数上限（デフォルト: 20） |
| offset | integer | No | オフセット（デフォルト: 0） |

**全パラメータ省略時のデフォルト動作:**
- フィルタ条件なしで最新20件を返却（created_at降順）
- is_deleted = TRUE のメッセージは常に除外

**検索優先度:**
1. 全文検索スコア（pg_trgm類似度）※query指定時
2. emotion_total（高い方が優先）
3. 作成日時（新しい方が優先）

**レスポンス例:**
```json
{
  "total": 3,
  "messages": [
    {
      "id": 42,
      "session_date": "2026-03-07",
      "category": "knowledge",
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

### 3.3 forget — 記憶を論理削除 **(Phase 2実装予定)**

指定した記憶を論理削除する（is_deleted = TRUE）。物理削除は行わない。

**入力パラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| message_id | integer | Yes | 削除対象のメッセージID |
| reason | string | No | 削除理由（messages.deleted_reason に保存） |

**処理フロー:**
1. 対象メッセージの is_deleted を TRUE に更新
2. reason が指定されていれば deleted_reason カラムに保存
3. recall の検索結果からは除外される

**レスポンス例:**
```json
{
  "message_id": 42,
  "status": "forgotten"
}
```

### 3.4 reflect — 記憶を振り返る **(Phase 2実装予定)**

感情値が高い記憶を要約・抽出する。MEMORY.mdの自動整理や、セッション終了時の振り返りに利用。

**入力パラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| period | string | No | 振り返り期間: "today" / "week" / "month" / "all"（デフォルト: "week"） |
| top_n | integer | No | 取得する記憶の上限数（デフォルト: 10） |
| category | string | No | 種別でフィルタ |

**処理フロー:**
1. 指定期間内の記憶を感情値の合計降順で取得
2. 上位N件を返却
3. 各記憶にタグ情報を付与

**レスポンス例:**
```json
{
  "period": "week",
  "reflections": [
    {
      "id": 42,
      "speaker": "リサ",
      "content": "本番デプロイでDBマイグレーション漏れが発覚し2時間ダウン",
      "emotion": {"joy": 0, "anger": 200, "sorrow": 180, "fun": 0},
      "emotion_total": 380,
      "tags": ["本番障害", "PostgreSQL"],
      "session_date": "2026-03-05"
    }
  ]
}
```

## 4. エラーハンドリング

全ツール共通のエラーレスポンス形式:

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

## 5. MCP サーバー定義

```python
from mcp.server.fastmcp import FastMCP

# HTTPモード時はOAuth 2.1認証を有効にしてインスタンス生成
mcp = _createMcp()

@mcp.tool()
async def remember(content: str, speaker: str, ...) -> dict:
    """記憶を保存する"""
    return await remember_impl(...)

@mcp.tool()
async def recall(query: str = None, ...) -> dict:
    """記憶を検索する"""
    return await recall_impl(...)

# Phase 2 で追加予定
# @mcp.tool()
# async def forget(message_id: int, ...) -> dict: ...
# @mcp.tool()
# async def reflect(period: str = "week", ...) -> dict: ...
```

HTTPモード時は `/auth/pin` カスタムルートも追加される:

```python
@mcp.custom_route("/auth/pin", methods=["GET", "POST"])
async def pin_handler(request: Request) -> Response:
    ...
```
