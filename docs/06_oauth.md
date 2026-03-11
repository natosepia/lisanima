# OAuth 2.1 認証設計: lisanima

## 1. 概要

### 背景

lisanimaのHTTPモード（Streamable HTTP）はリモートクライアント（Desktop App等）からのアクセスを受け付ける。
認証なしでは誰でもリサになりすまして記憶の読み書きが可能なため、MCP仕様準拠のOAuth 2.1認証を実装する。

### 設計方針

| 項目 | 決定 | 理由 |
|------|------|------|
| 認証フレームワーク | FastMCP内蔵OAuth 2.0 AS | mcp SDK内蔵。自前実装不要 |
| 認可方式 | Authorization Code Grant + PKCE | MCP仕様必須。Desktop Appコネクタが使用 |
| ユーザー認証 | PIN認証 | 個人利用（ユーザー1人）のため最小構成 |
| トークン保存 | PostgreSQL（lisanima_db） | 既存インフラ活用。プロセス再起動でも失効しない |
| クライアント登録 | 動的クライアント登録（RFC 7591） | Desktop Appが自動的にclient_idを取得 |
| スコープ | なし（全権限） | 個人利用のため権限分離不要 |

### 対応仕様

| RFC | 内容 | FastMCPの対応 |
|-----|------|--------------|
| OAuth 2.1 (IETF DRAFT) | Authorization Code + PKCE | 対応済み |
| RFC 8414 | OAuth 2.0 Authorization Server Metadata | 対応済み |
| RFC 7591 | Dynamic Client Registration | 対応済み |
| RFC 7009 | Token Revocation | 対応済み |
| RFC 9728 | Protected Resource Metadata | 対応済み |

## 2. アーキテクチャ

### 責務分担

```
FastMCP（実装済み・変更不要）:
├── /.well-known/oauth-authorization-server   メタデータ公開
├── /.well-known/oauth-protected-resource/*   保護リソースメタデータ
├── /authorize                                認可エンドポイント（ハンドラ）
├── /token                                    トークン交換（ハンドラ）
├── /register                                 動的クライアント登録（ハンドラ）
├── /revoke                                   トークン無効化（ハンドラ）
├── BearerAuthBackend                         Bearerトークン検証ミドルウェア
├── RequireAuthMiddleware                     スコープ強制ミドルウェア
└── AuthContextMiddleware                     リクエストコンテキスト管理

lisanima（新規実装）:
├── OAuthAuthorizationServerProvider          ストレージ層（Protocol実装）
│   ├── get_client()                          クライアント情報取得
│   ├── register_client()                     クライアント登録
│   ├── authorize()                           認可URL生成（→ PIN入力画面へリダイレクト）
│   ├── load_authorization_code()             認可コード検索
│   ├── exchange_authorization_code()         認可コード → トークン交換
│   ├── load_refresh_token()                  リフレッシュトークン検索
│   ├── exchange_refresh_token()              トークンリフレッシュ
│   ├── load_access_token()                   アクセストークン検証
│   └── revoke_token()                        トークン無効化
├── PIN認可エンドポイント（/auth/pin）         PIN入力フォーム表示 + 検証
├── OAuthテーブル（DDL）                       PostgreSQLにトークン等を永続化
├── 認可画面（HTML）                           PIN入力フォーム
└── server.py 修正                            FastMCPにOAuth設定を渡す
```

### 認証フロー

```
Desktop App                    nginx (SSL)              lisanima (localhost:8765)
    │                              │                           │
    │  POST /lisanima/mcp          │                           │
    │─────────────────────────────→│  proxy → /mcp             │
    │                              │──────────────────────────→│
    │                              │  401 Unauthorized         │
    │←─────────────────────────────│←──────────────────────────│
    │                              │                           │
    │  GET /.well-known/oauth-authorization-server              │
    │─────────────────────────────→│──────────────────────────→│
    │  { authorize: "/authorize", token: "/token", ... }       │
    │←─────────────────────────────│←──────────────────────────│
    │                              │                           │
    │  POST /register (RFC 7591)                               │
    │─────────────────────────────→│──────────────────────────→│
    │  { client_id, client_secret }│                           │
    │←─────────────────────────────│←──────────────────────────│
    │                              │                           │
    │  ブラウザを開く               │                           │
    │  GET /authorize?client_id=...&code_challenge=...         │
    │                              │                           │
    │  FastMCP: authorize() 呼出   │                           │
    │  → provider.authorize() が   │                           │
    │    /auth/pin?... のURLを返却  │                           │
    │  → 302 Redirect to /auth/pin │                           │
    │                              │                           │
    │         なとせのブラウザ       │                           │
    │         ┌──────────────┐     │                           │
    │         │ PIN: [____]  │     │                           │
    │         │ [許可] [拒否] │     │                           │
    │         └──────────────┘     │                           │
    │         PIN入力 → 許可        │                           │
    │                              │  認可コード発行            │
    │  リダイレクト（code=xxx）      │                           │
    │←─────────────────────────────│←──────────────────────────│
    │                              │                           │
    │  POST /token { code, code_verifier }                     │
    │─────────────────────────────→│──────────────────────────→│
    │  { access_token, refresh_token, expires_in }             │
    │←─────────────────────────────│←──────────────────────────│
    │                              │                           │
    │  POST /lisanima/mcp  Authorization: Bearer <token>       │
    │─────────────────────────────→│──────────────────────────→│
    │  200 OK（MCP応答）            │                           │
    │←─────────────────────────────│←──────────────────────────│
```

### authorize() の動作詳細

FastMCPの `/authorize` ハンドラは `provider.authorize(client, params)` を呼び出し、**戻り値のURL文字列に302リダイレクト**する。
lisanimaの `authorize()` 実装は以下の流れ:

1. `AuthorizationParams`（client_id, redirect_uri, state, scopes, code_challenge等）を受け取る
2. パラメータを一時保存（DBまたはサーバーサイドセッション）
3. PIN入力画面のURL（`/auth/pin?session_id=xxx`）を返す
4. FastMCPがそのURLに302リダイレクト → ブラウザにPIN入力画面が表示される

PIN検証成功後、`/auth/pin` エンドポイントが:
1. 認可コードを生成・DB保存
2. `redirect_uri?code=xxx&state=xxx` にリダイレクト

```python
# authorize() のシグネチャ（FastMCP Protocol準拠）
async def authorize(
    self,
    client: OAuthClientInformationFull,
    params: AuthorizationParams,
) -> str:
    """認可URLを返す。PIN入力画面にリダイレクトさせる。"""
    # パラメータを一時保存
    session_id = await self._save_auth_session(client, params)
    # PIN入力画面のURLを返す
    return f"/auth/pin?session_id={session_id}"
```

## 3. ユーザー認証（PIN方式）

### 仕様

| 項目 | 値 |
|------|-----|
| 認証方式 | 固定PIN（数字 or 英数字） |
| PIN保存先 | `.env` の `OAUTH_PIN_HASH`（bcryptハッシュ） |
| PIN長 | 6文字以上推奨 |
| ブルートフォース対策 | 5回失敗で30秒ロックアウト（インメモリカウンタ） |
| 認可画面 | 最小HTML（PIN入力 + 許可/拒否ボタン） |

### PIN設定手順

```bash
# PINのbcryptハッシュを生成
python3 -c "import bcrypt; print(bcrypt.hashpw(b'your-pin-here', bcrypt.gensalt()).decode())"

# .env に追加
OAUTH_PIN_HASH=$2b$12$xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 認可画面（/auth/pin）

`authorize()` からリダイレクトされた `/auth/pin` エンドポイントがPIN入力フォームを返す。
POSTでPINを送信し、検証成功で認可コードを発行してリダイレクト。

**注意:** `/authorize` はFastMCPが管理するエンドポイント。lisanimaが独自にHTMLを返すのは `/auth/pin`。

```html
<!-- 最小構成。CSSは最低限のインラインスタイル -->
<form method="POST" action="/auth/pin">
  <input type="hidden" name="session_id" value="...">
  <label>PIN:</label>
  <input type="password" name="pin" required>
  <button type="submit" name="action" value="approve">許可</button>
  <button type="submit" name="action" value="deny">拒否</button>
</form>
```

### 将来の拡張余地

- 個人利用: PIN認証で十分
- SaaS化時: ユーザーテーブル追加 + メールアドレス/パスワード認証に切り替え
- PIN → パスワード への移行は `/auth/pin` エンドポイント内の検証ロジック変更のみ

## 4. トークン管理

### トークン種別

| トークン | 有効期限 | 用途 |
|----------|---------|------|
| access_token | 1時間 | MCPリクエストのBearer認証 |
| refresh_token | 30日 | access_tokenの再取得（PINなしで更新可能） |
| authorization_code | 5分 | 認可コード → トークン交換（1回限り） |

### トークン形式

- ランダム文字列（`secrets.token_urlsafe(32)`）
- JWT は使用しない（トークンイントロスペクションがDB参照のため、JWTの自己完結性が不要）

## 5. DBスキーマ

### テーブル一覧

既存の lisanima_db に以下のテーブルを追加する。

| テーブル名 | 分類 | 説明 |
|-----------|------|------|
| m_oauth_client | マスタ | 動的登録されたクライアント情報 |
| t_oauth_auth_session | トランザクション | authorize() → /auth/pin 間の一時データ |
| t_oauth_auth_code | トランザクション | 認可コード（5分失効、1回使い切り） |
| t_oauth_access_token | トランザクション | アクセストークン（1時間失効） |
| t_oauth_refresh_token | トランザクション | リフレッシュトークン（30日失効） |

DDLの詳細は [03_schema.md](03_schema.md) セクション3.6 / セクション6 を参照。

### m_oauth_client のJSONB設計について

`OAuthClientInformationFull` は以下のフィールドを持つ（RFC 7591準拠）:

```python
# OAuthClientMetadata（親クラス）
redirect_uris: list[AnyUrl]           # 必須
token_endpoint_auth_method: str       # "none" | "client_secret_post" | ...
grant_types: list[str]                # デフォルト: ["authorization_code", "refresh_token"]
response_types: list[str]             # デフォルト: ["code"]
scope: str | None
client_name, client_uri, logo_uri, contacts, tos_uri, policy_uri: ...
jwks_uri, jwks, software_id, software_version: ...

# OAuthClientInformationFull（子クラス）
client_id: str
client_secret: str | None
client_id_issued_at: int | None
client_secret_expires_at: int | None
```

個別カラムに分解するとフィールド追加のたびにALTER TABLEが必要。
JSONBなら `model_dump_json()` / `model_validate_json()` で透過的に保存・復元でき、
FastMCPのProtocolが求める `OAuthClientInformationFull` をそのまま返せる。

### 期限切れトークンの掃除

```sql
-- 定期実行（cronまたはlifespan内の定期タスク）
DELETE FROM t_oauth_auth_session WHERE expires_at < NOW();
DELETE FROM t_oauth_auth_code WHERE expires_at < NOW();
DELETE FROM t_oauth_access_token WHERE expires_at < NOW();
DELETE FROM t_oauth_refresh_token WHERE expires_at < NOW();
```

## 6. 実装ファイル構成

```
src/lisanima/
├── server.py                  # FastMCPにOAuth設定を渡す（修正）
├── db.py                      # get_connection() が @asynccontextmanager + lazy init に変更
├── auth/
│   ├── __init__.py
│   ├── provider.py            # OAuthAuthorizationServerProvider 実装
│   ├── pin.py                 # PIN検証ロジック + /auth/pin エンドポイント
│   └── templates/
│       └── pin.html           # PIN入力フォームテンプレート
├── repositories/
│   ├── session_repo.py        # 既存（変更なし）
│   ├── message_repo.py        # 既存（変更なし）
│   ├── tag_repo.py            # 既存（変更なし）
│   └── oauth_repo.py          # OAuthテーブルCRUD（新規）
└── tools/
    ├── remember.py            # 既存（変更なし）
    └── recall.py              # 既存（変更なし）
```

## 7. server.py の変更

HTTPモード時のみOAuth 2.1を有効にし、stdioモード時は認証なしで起動する。
`_createMcp()` 関数内で `_args.http` を判定し、FastMCPインスタンスの構築を分岐する。

```python
from lisanima.auth.provider import LisanimaOAuthProvider
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions

auth_settings = AuthSettings(
    issuer_url="https://quriowork.com",
    resource_server_url="https://quriowork.com/lisanima/mcp",
    client_registration_options=ClientRegistrationOptions(
        enabled=True,
        valid_scopes=[],
    ),
    revocation_options=RevocationOptions(enabled=True),
)

oauth_provider = LisanimaOAuthProvider()

mcp = FastMCP(
    "lisanima",
    lifespan=lifespan,
    auth=auth_settings,
    auth_server_provider=oauth_provider,
)
```

- `auth` を指定すると、FastMCPが自動的にOAuthエンドポイントを生成
- `auth_server_provider` にストレージ層を渡す
- `resource_server_url` はMCPエンドポイントのURLを指定（RFC 9728 Protected Resource Metadata用）
- **`issuer_url` はパスなしの `https://quriowork.com`** を指定する。3/26 auth specではMCPサーバーURLからパスを捨ててAuthorization Base URLを決定するため
- stdioモードでは `_createMcp()` 内で `auth` 引数を渡さない

### /auth/pin エンドポイントの追加

`authorize()` からリダイレクトされるPIN入力画面は、FastMCPの `custom_route` デコレータでOAuth認証スキップのカスタムエンドポイントとして登録する。

```python
from lisanima.auth.pin import handlePinGet, handlePinPost

@mcp.custom_route("/auth/pin", methods=["GET", "POST"])
async def pin_handler(request: Request) -> Response:
    if request.method == "GET":
        return await handlePinGet(request)
    return await handlePinPost(request)
```

`custom_route` はFastMCPが提供するデコレータで、BearerAuthBackendの認証対象外となる。

## 8. nginx設定

### パス設計

MCPサーバーURL: `https://quriowork.com/lisanima/mcp`

3/26 auth specではMCPサーバーURLの**パスを捨てて**Authorization Base URLが決定されるため、
OAuthエンドポイント（`/authorize`, `/token`, `/register`）はルートドメインに配置が必要。

→ Authorization Base URL: `https://quriowork.com`（パスなし）
→ ASメタデータ: `https://quriowork.com/.well-known/oauth-authorization-server`
→ PRメタデータ: `https://quriowork.com/.well-known/oauth-protected-resource/lisanima/mcp`

```nginx
# lisanima MCP本体
location /lisanima/ {
    proxy_pass http://127.0.0.1:8765/;
    proxy_set_header Host 127.0.0.1:8765;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # SSE / Streamable HTTP 対応
    proxy_http_version 1.1;
    proxy_set_header Connection '';
    chunked_transfer_encoding off;
    proxy_buffering off;
    proxy_cache off;
}

# RFC 9728 Protected Resource Metadata
location /.well-known/oauth-protected-resource/lisanima/ {
    proxy_pass http://127.0.0.1:8765/.well-known/oauth-protected-resource/;
    proxy_set_header Host 127.0.0.1:8765;
    # ...（同様のヘッダ設定）
}

# RFC 8414 Authorization Server Metadata
location = /.well-known/oauth-authorization-server {
    proxy_pass http://127.0.0.1:8765/.well-known/oauth-authorization-server;
    proxy_set_header Host 127.0.0.1:8765;
    # ...
}

# 3/26 spec fallback: OAuthエンドポイント群（ルートドメイン配置）
location = /authorize { proxy_pass http://127.0.0.1:8765/authorize; ... }
location = /token     { proxy_pass http://127.0.0.1:8765/token; ... }
location = /register  { proxy_pass http://127.0.0.1:8765/register; ... }

# PIN認証画面
location /auth/pin { proxy_pass http://127.0.0.1:8765/auth/pin; ... }
```

**重要:** 全てのlisanima向けlocationで `proxy_set_header Host 127.0.0.1:8765;` が必須。

**将来（6/18 spec、7月〜）:** PRMの `authorization_servers` でパス付きURL指定可能になるため、
全エンドポイントを `/lisanima/` 配下に寄せ直すことが可能になる。

## 9. セキュリティ考慮事項

| リスク | 対策 |
|--------|------|
| トークン窃取 | SSL必須（nginx終端）。access_tokenは短命（1時間） |
| ブルートフォース（PIN） | 5回失敗で30秒ロックアウト（インメモリ） |
| リプレイ攻撃 | authorization_codeは1回使い切り + 5分有効期限 |
| PKCE | S256必須。code_verifier検証でinterception攻撃を防止 |
| DNS Rebinding | FastMCP内蔵のTransportSecuritySettings（localhost時自動有効） |
| パス推測 | `/mcp` → `/lisanima` で推測困難度を向上 |
| 期限切れトークン残留 | 定期DELETE（cron or lifespan内タスク） |
| 認可セッション固定 | auth_sessionsは10分で失効。PIN検証後に即削除 |

## 10. 環境変数

`.env` に追加:

```
# OAuth PIN認証
OAUTH_PIN_HASH=$2b$12$xxxxx...   # bcryptハッシュ
```

## 11. 将来の拡張（SaaS化時）

現在の設計はRule of Threeに基づき、個人利用（ユーザー1人）に最適化している。
SaaS化が必要になった場合の変更箇所:

| 変更箇所 | 現在 | SaaS化時 |
|----------|------|----------|
| ユーザー認証 | PIN（.env固定） | usersテーブル + パスワード認証 |
| 認可画面 | PIN入力のみ | サインアップ + ログイン + persona設定 |
| トークン | client_idのみ紐付け | user_id + persona_id紐付け |
| OAuthスコープ | なし | remember / recall / forget / reflect 個別制御 |
| データ分離 | persona_id='lisa'固定 | Row-Level Security or テナント分離 |

`persona_id` カラム（sessions, 将来のidentity等）が拡張余地として機能する。
