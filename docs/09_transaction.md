# トランザクション設計: lisanima

## 1. 概要

本ドキュメントは [02_architecture.md](02_architecture.md) セクション8「トランザクション設計」の詳細化である。
lisanimaのDB操作におけるトランザクション境界、分離レベル、エラーハンドリング方針を定義する。

- **DB**: 単一PostgreSQLインスタンス（分散トランザクション不要）
- **接続ライブラリ**: psycopg3（`AsyncConnectionPool`）
- **トランザクション制御**: `async with conn.transaction()` によるコンテキストマネージャ方式

テーブル定義・制約の詳細は [04_schema.md](04_schema.md)、認証フローは [07_oauth.md](07_oauth.md) を参照。

## 2. トランザクション方針

### 2.1 トランザクション境界

**原則: MCPコマンド（ツール呼び出し）1回 = トランザクション1つ**

psycopg3の `conn.transaction()` コンテキストマネージャにより、ブロック正常終了でCOMMIT、例外発生でROLLBACKが自動実行される。

```
LLMクライアント → MCPコマンド呼び出し
                    └→ db_pool.get_connection()
                        └→ conn.transaction()      ← トランザクション開始
                            ├→ Repository操作1
                            ├→ Repository操作2
                            └→ ...
                        ← 正常終了: COMMIT / 例外: ROLLBACK
```

### 2.2 autocommitの無効化

`AsyncConnectionPool` の初期化時に `autocommit=False` を指定している（`db.py`）。
psycopg3のデフォルト動作により、明示的な `conn.transaction()` ブロック外のSQL文は暗黙トランザクションで実行される。

**意図**: 全てのDB操作を明示的なトランザクション境界内で実行させ、意図しないautocommitを防ぐ。

## 3. 分離レベル

### READ COMMITTED（PostgreSQLデフォルト）を採用

**採用理由:**

1. **個人運用**: lisanimaは単一ユーザー（なとせ）の個人利用。同時に複数のMCPコマンドが競合するケースは限定的
2. **書き込み競合の低頻度**: MCPツール呼び出しはLLMの応答生成中に逐次実行されるため、同一リソースへの同時書き込みは発生しにくい
3. **ファントムリードの許容**: recallの検索結果が同一トランザクション内で変動しても、MCPコマンドは1回完結のため実害がない
4. **ロック競合の最小化**: より厳しい分離レベル（SERIALIZABLE等）はロック範囲が広がり、OAuth認証フローとMCPコマンドの並行実行時にデッドロックリスクが増す

**将来の再検討条件**: マルチユーザー対応（Phase 4.0）時に、書き込み競合頻度の増加に応じて分離レベルの引き上げを検討する。

## 4. コマンド別トランザクション設計

### 4.1 remember（記憶保存）

**トランザクション境界**: ツールハンドラ全体を1トランザクションで包む

```python
async with db_pool.get_connection() as conn:
    async with conn.transaction():
        session = await session_repo.findOrCreateSession(conn, ...)
        message = await message_repo.insertMessage(conn, ...)
        if tags:
            tag_records = await tag_repo.findOrCreateTags(conn, tags)
            await tag_repo.linkMessageTags(conn, message["id"], ...)
```

**整合性要件:**
- セッション取得/作成 → メッセージINSERT → タグ紐付けが不可分（原子性）
- セッションの `findOrCreateSession` は内部で `SELECT ... FOR UPDATE` を使用し、並行INSERTのrace conditionを防止
- タグの `findOrCreateTags` は `INSERT ... ON CONFLICT DO NOTHING` で冪等性を担保

**ネストトランザクション**: `findOrCreateSession` 内部にも `conn.transaction()` がある。psycopg3はネストされた `transaction()` をSAVEPOINTとして処理するため、内部ロールバックが外部トランザクション全体に波及しない。

### 4.2 recall（記憶検索）

**トランザクション境界**: 明示的なトランザクションブロックなし（暗黙トランザクション）

```python
async with db_pool.get_connection() as conn:
    result = await message_repo.searchMessages(conn, ...)
```

**整合性要件:**
- 読み取り専用操作のため、明示トランザクション不要
- `searchMessages` 内で件数取得（COUNT）とデータ取得（SELECT）を別クエリで実行するが、READ COMMITTED下で両者の間にINSERTが挟まる可能性は理論上ある。個人運用では実害なし
- タグの一括取得（`_getMessageTagsBatch`）もデータ取得直後に同一接続で実行されるため、一貫性は実質的に保たれる

### 4.3 forget / organize / rulebook / topic_manage（未実装コマンド）

Phase 2以降で実装予定。トランザクション方針は以下を適用する:

| コマンド | 操作種別 | トランザクション方針 |
|---------|---------|-------------------|
| forget | UPDATE（論理削除） | 明示トランザクション。対象メッセージの`is_deleted`と`deleted_reason`を原子的に更新 |
| organize | SELECT + INSERT/DELETE | 明示トランザクション。対象メッセージの検索 + タグ紐付けの追加/削除が不可分 |
| rulebook (set) | INSERT（イミュータブル追記） | 明示トランザクション。新バージョンINSERTの原子性を保証 |
| rulebook (retire) | UPDATE | 明示トランザクション |
| rulebook (list/get) | SELECT | 暗黙トランザクション（読み取り専用） |
| topic_manage (create/update/close) | INSERT/UPDATE | 明示トランザクション |
| topic_manage (list) | SELECT | 暗黙トランザクション（読み取り専用） |

### 4.4 OAuth認証フロー

OAuth操作はMCPセッション確立前に実行されるため、MCPコマンドとは独立したトランザクションを持つ。

| 操作 | トランザクション | 備考 |
|------|----------------|------|
| register_client | 明示 | クライアント情報のUPSERT |
| authorize | 明示 | 認可セッション保存 |
| exchange_authorization_code | 明示 | 認可コード削除 + AT/RT発行を原子的に実行 |
| exchange_refresh_token | 明示 | 旧RT削除 + 新AT/RT発行を原子的に実行（トークンローテーション） |
| revoke_token | 明示 | client_id単位でAT+RT両方を原子的に削除 |
| get_client / load_access_token | 暗黙 | 読み取り専用 |
| load_authorization_code / load_refresh_token | 暗黙 | 読み取り専用 |

**重要**: `exchange_authorization_code` と `exchange_refresh_token` は「削除→発行」の2段階操作を1トランザクションで実行する。分離すると、削除後の発行失敗でトークンが消失するリスクがある。

## 5. エラーハンドリング

### 5.1 ロールバック方針

psycopg3の `conn.transaction()` コンテキストマネージャにより、例外発生時は自動ROLLBACKされる。

**ツールハンドラでの例外処理パターン:**

```python
try:
    async with db_pool.get_connection() as conn:
        async with conn.transaction():
            ...  # DB操作
except RuntimeError as e:
    return {"error": "DB_CONNECTION_ERROR", "message": str(e)}
except Exception as e:
    logger.error("操作失敗", exc_info=True)
    return {"error": "INTERNAL_ERROR", "message": "予期しないエラーが発生しました"}
```

- `RuntimeError`: 接続プール枯渇やDB接続断を捕捉
- `Exception`: その他の予期しないエラーを捕捉（内部詳細はログのみ、LLMには一般化したメッセージを返す）
- MCP応答にスタックトレースを含めない（セキュリティ観点）

### 5.2 リトライ戦略

**現行方針: リトライしない**

- 個人運用のため一時的な競合は稀
- MCPコマンドは冪等ではない操作（remember等）を含むため、安易なリトライは重複保存を招く
- LLMがエラー応答を受け取った場合、LLM自身がリトライ判断を行う

**将来の検討**: マルチユーザー対応時に、シリアライゼーション失敗（`40001`）に対する限定的なリトライを導入する可能性がある。

### 5.3 statement_timeout

接続プール初期化時に `statement_timeout=30000`（30秒）を設定している。
長時間実行クエリによるコネクション占有を防止する。

```python
kwargs={"options": "-c statement_timeout=30000"}
```

recallの全文検索（pg_trgm）が大量データに対して遅延した場合にタイムアウトで打ち切られる。

**タイムアウト時のエラーレスポンス:**

psycopg3はPostgreSQLの `statement_timeout` によるクエリキャンセルを `psycopg.errors.QueryCanceled` 例外として送出する。現状の例外ハンドラ（セクション5.1）では汎用の `Exception` で捕捉されるため、LLMクライアントには以下のレスポンスが返る:

```json
{
  "error": "INTERNAL_ERROR",
  "message": "予期しないエラーが発生しました"
}
```

将来的に `QueryCanceled` を個別に捕捉し、専用エラーコード `QUERY_TIMEOUT` を返すことを検討する。これにより、LLMクライアント側でタイムアウトを識別し、検索条件の絞り込みを提案する等の適切なリカバリが可能になる。

```python
# 将来の実装イメージ
except psycopg.errors.QueryCanceled:
    return {"error": "QUERY_TIMEOUT", "message": "検索がタイムアウトしました。条件を絞り込んでください"}
```

**NFR-P001（recall検索応答1秒以内）との関係:**

`statement_timeout=30秒` はクエリ暴走に対する安全弁であり、NFR-P001の「1秒以内」要件とは目的が異なる。1秒要件はインデックス最適化・クエリチューニング等のパフォーマンス施策で対応すべきであり、statement_timeoutに依存して達成するものではない。

## 6. デッドロック対策

### 個人運用での現実的な対策

lisanimaは個人運用であり、同時実行されるトランザクション数は限定的。以下の対策で十分とする。

**1. ロック取得順の統一**

`findOrCreateSession` では `SELECT ... FOR UPDATE` で行ロックを取得する。複数テーブルにまたがるロック取得時は、常に `sessions → messages → tags` の順序でアクセスする。

**2. トランザクション粒度の最小化**

トランザクションは必要最小限の操作のみを包む。recallのような読み取り専用操作には明示トランザクションを使用しない。

**3. PostgreSQLのデッドロック検出**

PostgreSQLはデッドロックを自動検出し、一方のトランザクションを `ERROR 40P01 (deadlock_detected)` でアボートする。statement_timeout（30秒）もフォールバックとして機能する。

**4. MCPの逐次実行特性**

MCPプロトコルの特性上、LLMクライアントは1つのツール呼び出しの応答を待ってから次のツールを呼び出す。stdioモードでは実質的にシングルスレッド実行となるため、デッドロックは構造的に発生しにくい。HTTPモードでも、同一クライアントからの並行リクエストはMCPセッション単位で逐次化される。

## 7. 接続プール設計

### 7.1 AsyncConnectionPool の設定

```python
AsyncConnectionPool(
    conninfo=dsn,
    min_size=2,       # 最小接続数
    max_size=5,       # 最大接続数
    open=False,       # 明示的にopen()を呼ぶまで接続しない
    kwargs={
        "row_factory": dict_row,              # 結果をdict形式で取得
        "autocommit": False,                  # 明示トランザクション制御
        "options": "-c statement_timeout=30000",  # 30秒タイムアウト
    },
)
```

**設定根拠:**
- `min_size=2`: MCPコマンドとOAuth認証フローが並行して接続を使う可能性を考慮。個人運用では2本で十分
- `max_size=5`: バーストアクセス時のバッファ。PostgreSQL側の`max_connections`（デフォルト100）に対して控えめに設定
- `open=False`: lifespan内で明示的にopen()を呼ぶため

### 7.2 Lazy Init パターン

`get_connection()` は `@asynccontextmanager` + lazy init で実装している。

```python
@asynccontextmanager
async def get_connection(self):
    if not self._pool:
        await self.open()
    async with self._pool.connection() as conn:
        yield conn
```

**背景**: FastMCPのlifespanはMCPセッション開始時に発火するが、OAuthエンドポイント（`/register`, `/authorize` 等）はMCPセッション確立前にアクセスされる。lifespan未発火の状態でもDB接続を取得できるよう、lazy initパターンを採用した。

### 7.3 接続のライフサイクル

```
サーバー起動
  │
  ├→ HTTPモード: OAuthリクエスト → get_connection() → lazy init（プール初期化）
  │
  ├→ MCPセッション確立 → lifespan発火 → db_pool.open()（初期化済みなら何もしない）
  │
  ├→ MCPコマンド実行 → get_connection() → プールから接続取得 → 操作 → 接続返却
  │
  └→ サーバー終了 → lifespan finally → db_pool.close()（プール解放）
```

## 8. N+1問題への対策

### 現在の対策

**recallのタグ取得**: `_getMessageTagsBatch()` で、検索結果のメッセージIDリストを `IN (...)` 句にまとめて1クエリで一括取得している。

```python
message_ids = [row["id"] for row in rows]
if message_ids:
    tags_by_msg = await _getMessageTagsBatch(conn, message_ids)
```

これにより、メッセージ件数に関わらずタグ取得は1クエリで完了する（N+1 → 1+1）。

### JOINとバッチ処理の使い分け

| パターン | 採用基準 | 現在の適用箇所 |
|---------|---------|--------------|
| JOIN | 1:1 または N:1 のリレーション | `messages JOIN sessions`（recall検索時） |
| バッチ `IN(...)` | N:M のリレーション、結果をアプリ側でマッピング | `_getMessageTagsBatch`（メッセージ×タグ） |
| ループSELECT | 避ける。やむを得ない場合は件数上限を設ける | `findOrCreateTags`（タグ数は少数のため許容） |

**`findOrCreateTags` のループについて**: タグごとに `INSERT ... ON CONFLICT` を実行している。1メッセージに付与するタグ数は通常5個以下であり、executemany化の恩恵が小さいため現状はループで許容。大量タグの一括登録が必要になった場合は `unnest()` + CTE パターンへの移行を検討する。
