# 11. シーケンス図

## 1. 概要

本ドキュメントは lisanima の主要な処理フローを Mermaid シーケンス図で記述する。
クラス構造は [10_class_diagram.md](./10_class_diagram.md)、トランザクション境界の設計方針は [09_transaction.md](./09_transaction.md) を参照。

対象フローは以下の3本。

| # | フロー | 系統 |
|---|--------|------|
| 1 | remember | 書き込み系代表 |
| 2 | recall | 読み取り系代表 |
| 3 | OAuth 認証 | 認証フロー全体 |

## 2. remember シーケンス図

記憶の保存フロー。セッション取得 → メッセージ保存 → タグ紐付けを **1トランザクション** で実行する。
ツールインターフェースの詳細は [03_mcp_interface.md](./03_mcp_interface.md) を参照。

```mermaid
sequenceDiagram
    autonumber
    participant Client as LLMクライアント
    participant Server as server.py
    participant Remember as remember.py
    participant DB as AsyncDatabasePool
    participant SRepo as session_repo
    participant MRepo as message_repo
    participant TRepo as tag_repo
    participant PG as PostgreSQL

    Client->>Server: MCP tool call: remember(content, speaker, ...)
    Server->>Remember: remember(content, speaker, ...)

    Remember->>Remember: _validateParams()
    alt バリデーションエラー
        Remember-->>Server: {error: "INVALID_PARAMETER"}
        Server-->>Client: エラーレスポンス
    end

    Remember->>DB: get_connection()
    DB-->>Remember: conn

    Note over Remember,PG: トランザクション開始

    Remember->>SRepo: findOrCreateSession(conn, date, project)
    SRepo->>PG: SELECT ... FOR UPDATE / INSERT
    PG-->>SRepo: session dict
    SRepo-->>Remember: session

    Remember->>MRepo: insertMessage(conn, session_id, ...)
    MRepo->>PG: INSERT INTO messages ... RETURNING
    PG-->>MRepo: message dict
    MRepo-->>Remember: message

    opt tags が指定されている場合
        Remember->>TRepo: findOrCreateTags(conn, tags)
        TRepo->>TRepo: normalizeTagName() (NFKC正規化)
        TRepo->>PG: INSERT ... ON CONFLICT DO NOTHING / SELECT
        PG-->>TRepo: tag records
        TRepo-->>Remember: tag_records

        Remember->>TRepo: linkMessageTags(conn, message_id, tag_ids)
        TRepo->>PG: INSERT INTO message_tags ... ON CONFLICT DO NOTHING
    end

    Note over Remember,PG: トランザクション COMMIT

    Remember-->>Server: {message_id, session_id, emotion_total, status: "saved"}
    Server-->>Client: MCPレスポンス
```

### 補足

- `findOrCreateSession` は `FOR UPDATE` によるロックで並行リクエスト時の競合を防止する（詳細: [09_transaction.md](./09_transaction.md)）
- emotion は4カラム独立化済み（#9）。エンコード/デコード処理は不要
- エラー発生時はトランザクションが自動ロールバックされ、エラーレスポンスを返す

## 3. recall シーケンス図

記憶の検索フロー。動的 WHERE 構築 → pg_trgm 類似検索 → タグ一括取得の流れ。
スキーマ定義は [04_schema.md](./04_schema.md) を参照。

```mermaid
sequenceDiagram
    autonumber
    participant Client as LLMクライアント
    participant Server as server.py
    participant Recall as recall.py
    participant DB as AsyncDatabasePool
    participant MRepo as message_repo
    participant PG as PostgreSQL

    Client->>Server: MCP tool call: recall(query, tags, ...)
    Server->>Recall: recall(query, tags, ...)

    Recall->>Recall: _validateParams(limit, offset, date_from, date_to, ..., mode, since, tags, tags_empty, source)
    alt バリデーションエラー
        Recall-->>Server: {error: "INVALID_PARAMETER"}
        Server-->>Client: エラーレスポンス
    end

    Recall->>DB: get_connection()
    DB-->>Recall: conn

    Recall->>MRepo: searchMessages(conn, query, tags, ...)

    opt query が指定されている場合
        MRepo->>PG: SET pg_trgm.similarity_threshold = 0.1
    end

    MRepo->>PG: SELECT COUNT(*) ... (件数取得)
    PG-->>MRepo: total

    MRepo->>PG: SELECT ... JOIN sessions (データ取得 + pg_trgm類似度ORDER)
    PG-->>MRepo: rows

    opt 検索結果にメッセージがある場合
        MRepo->>MRepo: _getMessageTagsBatch(conn, message_ids)
        MRepo->>PG: SELECT FROM message_tags JOIN tags WHERE IN(...)
        PG-->>MRepo: tags_by_msg
    end

    MRepo->>MRepo: emotion_total を算出（joy + anger + sorrow + fun）
    MRepo-->>Recall: {total, messages}

    Recall->>Recall: datetime → ISO文字列変換
    Recall-->>Server: {total, messages}
    Server-->>Client: MCPレスポンス
```

### 補足

- recall はデータ変更を伴わないため、明示的なトランザクション制御は行わない（autocommit=False のため暗黙トランザクション内で実行）
- タグの一括取得（`_getMessageTagsBatch`）により N+1 問題を回避している
- pg_trgm の `%` 演算子で GIN インデックスを活用（similarity_threshold=0.1 で日本語短文に対応）

## 4. OAuth 認証フロー シーケンス図

Desktop App からリモート接続する際の OAuth 2.1 認証フロー全体。
DCR（動的クライアント登録）→ 認可 → PIN 認証 → トークン交換の一連の流れ。
OAuth 実装の詳細は [07_oauth.md](./07_oauth.md)、セキュリティ要件は [06_security.md](./06_security.md) を参照。

```mermaid
sequenceDiagram
    autonumber
    participant App as Desktop App
    participant Nginx as nginx
    participant FastMCP as FastMCP<br>(OAuth Handler)
    participant Provider as LisanimaOAuthProvider
    participant Pin as pin.py
    participant ORepo as oauth_repo
    participant PG as PostgreSQL

    Note over App,PG: Phase 1: 動的クライアント登録 (RFC 7591)

    App->>Nginx: POST /register
    Nginx->>FastMCP: proxy
    FastMCP->>Provider: register_client(client_info)
    Provider->>Provider: client_id, client_secret 生成
    Provider->>ORepo: saveClient(conn, client_id, json)
    ORepo->>PG: INSERT INTO m_oauth_client
    Provider-->>FastMCP: (完了)
    FastMCP-->>App: {client_id, client_secret}

    Note over App,PG: Phase 2: 認可リクエスト + PIN 認証

    App->>Nginx: GET /authorize?response_type=code&client_id=...&code_challenge=...
    Nginx->>FastMCP: proxy
    FastMCP->>Provider: authorize(client, params)
    Provider->>ORepo: saveAuthSession(conn, ...)
    ORepo->>PG: INSERT INTO t_oauth_auth_session
    PG-->>ORepo: session_id
    Provider-->>FastMCP: "/auth/pin?session_id=xxx"
    FastMCP-->>App: 302 Redirect → /auth/pin?session_id=xxx

    App->>Nginx: GET /auth/pin?session_id=xxx
    Nginx->>Pin: handlePinGet(request)
    Pin->>ORepo: loadAuthSession(conn, session_id)
    ORepo->>PG: SELECT FROM t_oauth_auth_session
    PG-->>Pin: session data
    Pin-->>App: PIN入力フォーム (HTML)

    App->>Nginx: POST /auth/pin (session_id, pin, action=approve)
    Nginx->>Pin: handlePinPost(request)
    Pin->>Pin: _checkLockout()
    Pin->>Pin: _verifyPin(pin) [bcrypt]

    alt PIN不一致
        Pin->>Pin: _recordFailure()
        Pin-->>App: 401 エラー表示（残り回数）
    end

    Pin->>Pin: _resetFailures()

    Note over Pin,PG: トランザクション開始
    Pin->>ORepo: saveAuthCode(conn, ...)
    ORepo->>PG: INSERT INTO t_oauth_auth_code
    PG-->>ORepo: code
    Pin->>ORepo: deleteAuthSession(conn, session_id)
    ORepo->>PG: DELETE FROM t_oauth_auth_session
    Note over Pin,PG: トランザクション COMMIT

    Pin-->>App: 302 Redirect → redirect_uri?code=xxx&state=yyy

    Note over App,PG: Phase 3: トークン交換

    App->>Nginx: POST /token (grant_type=authorization_code, code=xxx, code_verifier=...)
    Nginx->>FastMCP: proxy
    FastMCP->>Provider: load_authorization_code(client, code)
    Provider->>ORepo: loadAuthCode(conn, code)
    ORepo->>PG: SELECT FROM t_oauth_auth_code
    PG-->>Provider: AuthorizationCode

    FastMCP->>FastMCP: PKCE検証 (code_verifier ↔ code_challenge)

    FastMCP->>Provider: exchange_authorization_code(client, code)

    Note over Provider,PG: トランザクション開始
    Provider->>ORepo: deleteAuthCode(conn, code)
    ORepo->>PG: DELETE FROM t_oauth_auth_code
    Provider->>ORepo: saveAccessToken(conn, ...)
    ORepo->>PG: INSERT INTO t_oauth_access_token
    Provider->>ORepo: saveRefreshToken(conn, ...)
    ORepo->>PG: INSERT INTO t_oauth_refresh_token
    Note over Provider,PG: トランザクション COMMIT

    Provider-->>FastMCP: OAuthToken
    FastMCP-->>App: {access_token, refresh_token, expires_in}

    Note over App,PG: 以降: MCP通信（Bearer トークンで認証）
```

### 補足

- PKCE 検証（`code_verifier` と `code_challenge` の照合）は FastMCP 内部で実行される
- 認可コードは1回使い切り（交換時に即削除）
- PIN 認証はブルートフォース対策として、5回失敗で30秒のロックアウトを実施（インメモリカウンタ）
- nginx のプロキシ構成については [07_oauth.md](./07_oauth.md) を参照

## 5. トランザクション境界の注記

各フローのトランザクション境界は以下の方針に基づく。詳細は [09_transaction.md](./09_transaction.md) を参照。

| フロー | トランザクション範囲 | 理由 |
|--------|---------------------|------|
| remember | セッション取得〜メッセージ保存〜タグ紐付け | 途中失敗時に中途半端なデータが残ることを防ぐ |
| recall | 明示的トランザクションなし | 参照のみ。暗黙トランザクション（autocommit=False）で十分 |
| OAuth: PIN認証 | 認可コード保存〜セッション削除 | 認可コード発行とセッション削除を原子的に実行 |
| OAuth: トークン交換 | 認可コード削除〜AT発行〜RT発行 | 1回使い切りの認可コード削除とトークンペア発行を原子的に実行 |
| OAuth: トークン無効化 | AT削除〜同一クライアントのRT削除（またはその逆） | RFC 7009 推奨: 関連トークンのペア削除を原子的に実行 |
