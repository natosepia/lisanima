# アーキテクチャ設計: lisanima

## 1. システム構成図

```mermaid
flowchart LR
    %% ===== クライアント層 =====
    subgraph clients ["LLMクライアント"]
        cc["Claude Code<br/>(VSCode)"]
        da["Desktop App"]
    end

    %% ===== 接続経路 =====
    cc -- "stdio" --> tools
    da -- "HTTPS" --> nginx
    nginx["nginx<br/>(SSL終端)"] -- "HTTP<br/>(OAuth 2.1)" --> tools

    %% ===== lisanima サーバー =====
    subgraph server ["lisanima MCPサーバー (Python)"]
        tools["MCP Tools Layer<br/>remember / forget / recall<br/>rulebook / topic_manage / organize"]
        repo["Repository Layer"]
        db["Database Layer<br/>(psycopg3 ConnectionPool)"]
        tools --> repo --> db
    end

    %% ===== lisanima CLI (Phase 2) =====
    cli["lisanima CLI<br/>(Phase 2)<br/>Hooks・cron"] -- "直接利用" --> repo

    %% ===== PostgreSQL =====
    subgraph pg ["PostgreSQL — lisanima_db"]
        direction TB
        pg_core["コア<br/>sessions / messages / tags"]
        pg_topic["トピック<br/>topics / roles"]
        pg_rule["ルールブック<br/>rulebooks"]
        pg_oauth["OAuth<br/>client / token"]
        pg_core ~~~ pg_topic ~~~ pg_rule ~~~ pg_oauth
    end

    db --> pg
```

### アクセス経路の使い分け

| 経路 | トリガー | 用途 |
|------|---------|------|
| MCPサーバー | LLM（リサ）が自発的に判断 | 対話中のremember/forget/recall/rulebook/topic_manage/organize |
| CLI | Hooks・cron等の機械的イベント | セッション開始時の自動recall、終了時の自動remember |

MCPサーバーとCLIはRepository/Database Layerを共有し、同一DBにアクセスする。

## 2. 技術選定

| コンポーネント | 技術 | 選定理由 |
|--------------|------|---------|
| 言語 | Python 3.12+ | MCP SDK公式対応、チームの習熟度 |
| パッケージ管理 | uv | pip比で10-100倍高速、ロックファイル対応 |
| MCPフレームワーク | FastMCP（`mcp` Python SDK内蔵） | 公式SDK、stdio/Streamable HTTP対応、OAuth 2.0 AS内蔵 |
| DB | PostgreSQL | crypto_trade_botと同一インスタンス活用、全文検索が強力 |
| DB接続 | psycopg3 | asyncio対応、コネクションプール内蔵 |
| 全文検索 | pg_trgm + GINインデックス | 日本語トライグラム検索、追加拡張不要 |
| ルール同期 | rulesync or 自作 | CLAUDE.md ↔ GEMINI.md の同期（Phase 3） |

### SQLite を採用しなかった理由
- crypto_trade_botで既にPostgreSQLが稼働中（インフラ追加コストゼロ）
- pg_trgmによる日本語全文検索がSQLite FTS5より設定が容易
- 将来的にリモートアクセス（複数マシンからリサの記憶を参照）の可能性

## 3. ディレクトリ構成

```
lisanima/
├── docs/                          設計ドキュメント
│   ├── 01_requirements.md
│   ├── 02_architecture.md
│   ├── 03_mcp_interface.md
│   ├── 04_schema.md
│   ├── 05_migration.md
│   └── 06_oauth.md
├── migrations/
│   └── 002_oauth.sql              OAuth + m_category + source列マイグレーション
├── src/
│   └── lisanima/
│       ├── __init__.py
│       ├── server.py              MCPサーバーエントリポイント
│       ├── db.py                  DB接続・コネクションプール（lazy init対応）
│       ├── auth/
│       │   ├── __init__.py
│       │   ├── provider.py        OAuthAuthorizationServerProvider 実装
│       │   ├── pin.py             PIN検証ロジック + /auth/pin エンドポイント
│       │   └── templates/
│       │       └── pin.html       PIN入力フォームテンプレート
│       ├── repositories/
│       │   ├── __init__.py
│       │   ├── session_repo.py    SessionRepository
│       │   ├── message_repo.py    MessageRepository
│       │   ├── tag_repo.py        TagRepository
│       │   └── oauth_repo.py      OAuthテーブルCRUD
│       └── tools/
│           ├── __init__.py
│           ├── remember.py        記憶保存ツール
│           └── recall.py          記憶検索ツール
├── sql/
│   └── init.sql                   DDL（テーブル作成）
├── tests/
│   └── ...
├── pyproject.toml
└── .env                           DB接続情報 + OAUTH_PIN_HASH（git管理外）
```

## 4. レイヤー設計

### 4.1 MCP Tools Layer
- MCPプロトコルのツール定義
- 入力バリデーション
- Repository Layerの呼び出し
- LLMに返すレスポンスの整形

### 4.2 Repository Layer
- ビジネスロジック（検索条件の組み立て、感情値の計算等）
- SQLの発行はここに集約
- 1リポジトリ = 1テーブル（+ 関連テーブル）

### 4.3 Database Layer
- psycopg3のコネクションプール管理（`AsyncDatabasePool`）
- DB接続情報の読み込み（.env）
- トランザクション制御
- `get_connection()` は `@asynccontextmanager` + lazy init パターン。OAuth認証フローなどMCPセッション確立前のリクエストにも対応

## 5. 通信方式

### 5.1 MCP Protocol（stdio）
- Claude Code / Gemini CLI → lisanima MCPサーバー間の通信
- JSON-RPC 2.0ベース
- ネットワークを介さないローカル通信（セキュリティリスク最小）

```
LLMクライアント  --stdin-->  lisanima MCPサーバー
                <--stdout--
```

### 5.2 Streamable HTTP（リモート接続）
- Desktop App等のリモートクライアント → nginx → lisanima MCPサーバー
- OAuth 2.1認証（PIN方式）実装済み。詳細: [06_oauth.md](06_oauth.md)
- systemdサービス `lisanima.service` で `--http` モード稼働中

```
Desktop App  --HTTPS-->  nginx (SSL終端)  --HTTP-->  lisanima (127.0.0.1:8765)
                         /lisanima/                  → /
```

| 項目 | 値 |
|------|-----|
| MCPエンドポイント | `https://quriowork.com/lisanima/mcp` |
| issuer_url | `https://quriowork.com`（パスなし。3/26 auth specの要件） |
| resource_server_url | `https://quriowork.com/lisanima/mcp` |
| nginxプロキシ | `/lisanima/` → `http://127.0.0.1:8765/` |
| 認証 | OAuth 2.1（PIN方式） |

### Claude Code側の設定（ユーザーレベル）

プロジェクト横断で使うため、ユーザーレベル（`~/.claude.json`）に登録する。

```bash
claude mcp add --scope user lisanima -- uv run --directory /home/natosepia/project/lisanima python -m lisanima.server
```

## 6. 将来の拡張ポイント

| 拡張 | 概要 | 想定Phase |
|------|------|----------|
| lisanima CLI | Hooks・cronからDB操作するためのコマンドラインI/F | Phase 2.0 |
| Hooks連携 | セッション開始時の自動recall、終了時の自動remember | Phase 2.0 |
| 埋め込みベクトル | 意味検索（セマンティック検索）の追加 | Phase 3+ |
| Web UI | 記憶の閲覧・編集用ダッシュボード | Phase 3+ |
| マルチユーザー | 複数AI人格の記憶管理 | Phase 3+ |
