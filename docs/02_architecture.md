# アーキテクチャ設計: lisanima

## 1. システム構成図

```
┌─────────────────────────────────────────────┐
│  LLMクライアント                              │
│  ┌──────────────┐  ┌──────────────┐          │
│  │ Claude Code  │  │ Gemini CLI   │  ...     │
│  │ (VSCode)     │  │              │          │
│  └──────┬───────┘  └──────┬───────┘          │
│         │                  │                  │
│         │  MCP Protocol    │  MCP Protocol    │
│         │  (stdio)         │  (stdio)         │
└─────────┼──────────────────┼──────────────────┘
          │                  │
          ▼                  ▼
┌─────────────────────────────────────────────┐
│  lisanima MCPサーバー (Python)               │
│  ※ LLMが自発的に呼び出す経路                  │
│                                              │
│  ┌─────────────────────────────────────┐     │
│  │  MCP Tools Layer                    │     │
│  │  ├── remember()   記憶を保存         │     │
│  │  ├── recall()     記憶を検索         │     │
│  │  ├── forget()     記憶を削除         │     │
│  │  └── reflect()    記憶を振り返る     │     │
│  └──────────────┬──────────────────────┘     │
│                 │                             │
│  ┌──────────────▼──────────────────────┐     │
│  │  Repository Layer                   │     │
│  │  ├── SessionRepository              │     │
│  │  ├── MessageRepository              │     │
│  │  └── TagRepository                  │     │
│  └──────────────┬──────────────────────┘     │
│                 │                             │
│  ┌──────────────▼──────────────────────┐     │
│  │  Database Layer (psycopg3)          │     │
│  │  └── ConnectionPool                 │     │
│  └──────────────┬──────────────────────┘     │
└─────────────────┼────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────┐
│  PostgreSQL                                  │
│  └── lisanima DB                             │
│      ├── sessions        セッション単位      │
│      ├── messages        発言単位            │
│      ├── (GINインデックス  pg_trgm全文検索)   │
│      ├── tags            連想記憶            │
│      └── message_tags    多対多リレーション   │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│  lisanima CLI (Phase 2)                      │
│  ※ Hooks等の外部トリガーから機械的に呼び出す経路 │
│                                              │
│  $ lisanima recall --recent 5                │
│  $ lisanima remember --content "..." --auto  │
│                                              │
│  Repository / Database Layer を直接利用       │
│  （MCPサーバーを経由しない）                    │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
              PostgreSQL（同一DB）
```

### アクセス経路の使い分け

| 経路 | トリガー | 用途 |
|------|---------|------|
| MCPサーバー | LLM（リサ）が自発的に判断 | 対話中のremember/recall/forget/reflect |
| CLI | Hooks・cron等の機械的イベント | セッション開始時の自動recall、終了時の自動remember |

MCPサーバーとCLIはRepository/Database Layerを共有し、同一DBにアクセスする。

## 2. 技術選定

| コンポーネント | 技術 | 選定理由 |
|--------------|------|---------|
| 言語 | Python 3.12+ | MCP SDK公式対応、チームの習熟度 |
| パッケージ管理 | uv | pip比で10-100倍高速、ロックファイル対応 |
| MCPフレームワーク | `mcp` Python SDK | 公式SDK、stdio通信対応 |
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
│   ├── 03_schema.md
│   ├── 04_mcp-tools.md
│   └── 05_migration.md
├── src/
│   └── lisanima/
│       ├── __init__.py
│       ├── server.py              MCPサーバーエントリポイント
│       ├── cli.py                CLIエントリポイント（Phase 2）
│       ├── db.py                  DB接続・コネクションプール
│       ├── repositories/
│       │   ├── __init__.py
│       │   ├── session_repo.py    SessionRepository
│       │   ├── message_repo.py    MessageRepository
│       │   └── tag_repo.py        TagRepository
│       └── tools/
│           ├── __init__.py
│           ├── remember.py        記憶保存ツール
│           ├── recall.py          記憶検索ツール
│           ├── forget.py          記憶削除ツール
│           └── reflect.py         記憶振り返りツール
├── scripts/
│   └── migrate_markdown.py        Markdown → DB移行スクリプト
├── sql/
│   └── init.sql                   DDL（テーブル作成）
├── tests/
│   └── ...
├── pyproject.toml
└── .env                           DB接続情報（git管理外）
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
- psycopg3のコネクションプール管理
- DB接続情報の読み込み（.env）
- トランザクション制御

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
- OAuth 2.1認証必須（詳細: [06_oauth.md](06_oauth.md)）

```
Desktop App  --HTTPS-->  nginx (SSL終端)  --HTTP-->  lisanima (127.0.0.1:8765)
                         /lisanima/                  → /
```

| 項目 | 値 |
|------|-----|
| MCPエンドポイント | `https://quriowork.com/lisanima/mcp` |
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
| lisanima CLI | Hooks・cronからDB操作するためのコマンドラインI/F | Phase 2 |
| Hooks連携 | セッション開始時の自動recall、終了時の自動remember | Phase 2 |
| 埋め込みベクトル | 意味検索（セマンティック検索）の追加 | Phase 3+ |
| Web UI | 記憶の閲覧・編集用ダッシュボード | Phase 3+ |
| マルチユーザー | 複数AI人格の記憶管理 | Phase 3+ |
