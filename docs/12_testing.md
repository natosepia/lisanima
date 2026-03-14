# テスト戦略: lisanima

## 1. 概要

本ドキュメントはlisanimaプロジェクトのテスト戦略を定義する。
テストの分類・粒度・優先順位・インフラ構成を規定し、Phase 1残タスクの実装時に判断基準として機能することを目的とする。

**スコープ:**

- `src/lisanima/` 配下の全Pythonコード
- MCPツール（remember / recall / 今後追加されるコマンド群）
- OAuth 2.1認証フロー
- リポジトリ層のDB操作

**前提:**

- 個人運用規模のプロジェクトであり、過剰なテストインフラは導入しない
- DBはモックせず実DBを使用する（後述のセクション5を参照）

## 2. テスト分類

### 2.1 単体テスト（Unit Test）

外部依存（DB・ネットワーク）を持たない純粋関数・バリデーションロジックを対象とする。

| 対象 | 具体例 |
|------|--------|
| 感情値エンコード/デコード | `message_repo.encodeEmotion()` / `decodeEmotion()` |
| タグ名正規化 | `tag_repo.normalizeTagName()` |
| パラメータバリデーション | `tools/remember._validateParams()` / `tools/recall._validateParams()` |
| PINロックアウト判定 | `auth/pin._checkLockout()` / `_recordFailure()` / `_resetFailures()` |

**特徴:** DB接続不要、高速実行、デグレ検知に最適。

### 2.2 結合テスト（Integration Test）

DB接続を伴うリポジトリ層〜ツール層の結合動作を検証する。

| 対象 | 具体例 |
|------|--------|
| リポジトリ層 | `session_repo.findOrCreateSession()` のUPSERT動作 |
| リポジトリ層 | `message_repo.insertMessage()` / `searchMessages()` |
| リポジトリ層 | `tag_repo.findOrCreateTags()` の冪等性 |
| ツール層 | `remember()` の正常系（セッション作成→メッセージ保存→タグ紐付け） |
| ツール層 | `recall()` のフィルタ条件組み合わせ |
| OAuth | `oauth_repo` のトークンCRUD・期限切れ判定 |

**特徴:** テスト用DB（`lisanima_test_db`）に対して実行。トランザクション設計（[09_transaction.md](09_transaction.md)）の整合性も検証対象。

### 2.3 E2Eテスト（End-to-End Test）

MCPプロトコル経由でのツール呼び出しを検証する。Phase 1では対象外とし、Phase 2以降で必要に応じて導入を検討する。

| 対象 | 備考 |
|------|------|
| MCPクライアント→サーバー通信 | FastMCPのテストクライアントを利用 |
| OAuth認証→MCPツール呼び出し | HTTPモードの統合テスト |

**Phase 1で対象外とする理由:** FastMCPのプロトコル層は外部ライブラリの責務であり、lisanima固有のロジックはツール層・リポジトリ層で十分に検証できる。

## 3. テストフレームワーク

### 3.1 ライブラリ選定

| ライブラリ | 用途 | 備考 |
|-----------|------|------|
| pytest | テストランナー | デファクトスタンダード |
| pytest-asyncio | async関数のテスト | psycopg3の非同期APIに対応 |
| pytest-cov | カバレッジ計測 | htmlcov生成 |

### 3.2 pyproject.toml への追記

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.coverage.run]
source = ["src/lisanima"]
omit = ["src/lisanima/auth/templates/*"]

[tool.coverage.report]
show_missing = true
fail_under = 0
```

**`asyncio_mode = "auto"`** により、`async def test_*` 関数は自動的に非同期テストとして実行される。個別に `@pytest.mark.asyncio` を付与する必要がない。

## 4. DB依存テストのセットアップ方針

### 4.1 テスト用DB

本番DB（`lisanima_db`）とは別にテスト用DB（`lisanima_test_db`）を使用する。

```sql
CREATE DATABASE lisanima_test_db OWNER lisa;
```

スキーマは本番と同一のDDL（`migrations/` 配下）を適用する。テスト用DBのセットアップスクリプトで `psql -f` 実行するか、conftest.pyのセッションスコープfixtureで初期化する。

### 4.2 テストデータ分離: トランザクションロールバック方式

各テスト関数をトランザクション内で実行し、終了時にROLLBACKすることでデータを分離する。

```python
# conftest.py
@pytest.fixture
async def db_conn():
    """テスト用DB接続（各テスト後にROLLBACK）。"""
    pool = AsyncConnectionPool(
        conninfo=test_dsn,
        min_size=1, max_size=2, open=False,
        kwargs={"row_factory": dict_row, "autocommit": False},
    )
    await pool.open()
    async with pool.connection() as conn:
        # SAVEPOINTを利用してテストを分離
        async with conn.transaction() as tx:
            yield conn
            # テスト完了後、明示的にロールバック
            await tx.rollback()
    await pool.close()
```

**メリット:**

- TRUNCATE不要でテスト間の相互干渉を防止
- SERIAL値の消費を抑制（ロールバックで巻き戻る）
- テスト実行速度が速い（DDL操作なし）

**注意:** `conn.transaction()` のネストはpsycopg3がSAVEPOINTとして処理するため、テスト対象コード内のトランザクション制御と干渉しない（[09_transaction.md](09_transaction.md) セクション4.1参照）。

### 4.3 主要fixture

| fixture名 | スコープ | 用途 |
|-----------|---------|------|
| `db_conn` | function | テスト用DB接続（ロールバック付き） |
| `sample_session` | function | テスト用セッションレコードを事前投入 |
| `sample_message` | function | テスト用メッセージレコードを事前投入 |
| `sample_tags` | function | テスト用タグレコードを事前投入 |

fixture間の依存は `sample_message` → `sample_session` → `db_conn` のように連鎖させ、DRYを保つ。

### 4.4 emotion テストデータ

`encodeEmotion` / `decodeEmotion` の境界値テスト等で使用する代表的なemotion値を定数化し、テストケース間のマジックナンバー散乱を防ぐ。

```python
# tests/conftest.py または tests/unit/test_emotion.py
EMOTION_ZERO = {"joy": 0, "anger": 0, "sorrow": 0, "fun": 0}
EMOTION_MAX = {"joy": 255, "anger": 255, "sorrow": 255, "fun": 255}
EMOTION_JOY_ONLY = {"joy": 128, "anger": 0, "sorrow": 0, "fun": 0}
EMOTION_MIXED = {"joy": 80, "anger": 30, "sorrow": 0, "fun": 120}
```

## 5. モック戦略

### 5.1 モックしないもの（実物を使用）

| 対象 | 理由 |
|------|------|
| PostgreSQL | モックテストと本番の乖離によるバグ混入を防止。SQL構文・制約・型変換はDBでしか検証できない |
| psycopg3 | 接続プール・トランザクション・カーソルの振る舞いは実DBで検証する |

### 5.2 モックするもの

| 対象 | モック手段 | 理由 |
|------|-----------|------|
| `db_pool`（ツール層テスト時） | fixtureでテスト用プールに差し替え | 本番DBへの接続を防止 |
| `time.monotonic()`（PINロックアウトテスト） | `unittest.mock.patch` | 時刻依存のロックアウト判定を確定的にテスト |
| `os.getenv("OAUTH_PIN_HASH")` | `monkeypatch.setenv` | テスト用PINハッシュを注入 |
| `bcrypt.checkpw`（必要に応じて） | `unittest.mock.patch` | bcryptは低速なため、PINロジックの分岐テストでは省略可 |

### 5.3 ツール層テストでの `db_pool` 差し替え

`remember()` / `recall()` はモジュール直接の `db_pool` を参照しているため、テスト時は `monkeypatch` で差し替える。

```python
@pytest.fixture
async def mock_db_pool(db_conn):
    """ツール層テスト用: db_poolをテスト用接続に差し替え。"""
    class _TestPool:
        @asynccontextmanager
        async def get_connection(self):
            yield db_conn

    return _TestPool()
```

## 6. テストケース優先度

Phase 1で最初に書くべきテストを優先度順に示す。

### Priority 1: 純粋関数（単体テスト）

即座に書ける。DB不要。デグレ防止効果が高い。

| テスト対象 | 検証内容 |
|-----------|---------|
| `encodeEmotion()` | 正常系: 各感情値の組み合わせ |
| `encodeEmotion()` | 境界値: 0, 255, (0,0,0,0), (255,255,255,255) |
| `encodeEmotion()` | 異常系: 範囲外の値（-1, 256）で `ValueError` |
| `decodeEmotion()` | encode→decode の往復一致（プロパティテスト的） |
| `decodeEmotion()` | 負の整数からのデコード（符号付き32bit変換） |
| `normalizeTagName()` | 小文字化、全角→半角（NFKC）、前後空白除去 |
| `remember._validateParams()` | 空content / 空speaker の拒否 |
| `remember._validateParams()` | 不正な日付形式の拒否 |
| `remember._validateParams()` | 不正なemotionキー / 範囲外の値の拒否 |
| `recall._validateParams()` | limit < 1 / offset < 0 の拒否 |
| `recall._validateParams()` | date_from > date_to の逆転検出 |

### Priority 2: コアMCPコマンドの正常系（結合テスト）

remember / recall はlisanimaの核心機能。正常系の動作保証が最重要。

| テスト対象 | 検証内容 |
|-----------|---------|
| `remember()` 正常系 | メッセージ保存 → 返却値にmessage_id, session_id, status="saved" |
| `remember()` セッション自動作成 | 新規日付でのセッション作成 |
| `remember()` 既存セッション再利用 | 同日2回目のrememberで同一session_id |
| `remember()` タグ付き | tags指定時のタグ作成・紐付け |
| `recall()` 正常系 | パラメータ省略で最新20件取得 |
| `recall()` キーワード検索 | pg_trgmによる全文検索 |
| `recall()` タグフィルタ | AND検索の動作確認 |
| `recall()` 日付範囲フィルタ | date_from / date_to の境界 |
| `recall()` 論理削除除外 | `is_deleted=TRUE` のレコードが返らないこと |

### Priority 3: バリデーションエラー（結合テスト）

入力バリデーション（[06_security.md](06_security.md) セクション5参照）の動作確認。

| テスト対象 | 検証内容 |
|-----------|---------|
| `remember()` | 空content → `INVALID_PARAMETER` エラー |
| `remember()` | 不正emotion値 → `INVALID_PARAMETER` エラー |
| `recall()` | limit=0 → `INVALID_PARAMETER` エラー |
| `recall()` | 日付逆転 → `INVALID_PARAMETER` エラー |

### Priority 4: OAuth関連（結合テスト）

認証フロー（[07_oauth.md](07_oauth.md) 参照）のDB操作を検証。

| テスト対象 | 検証内容 |
|-----------|---------|
| `oauth_repo.saveClient` / `loadClient` | クライアント情報のUPSERT |
| `oauth_repo.saveAuthCode` / `loadAuthCode` | 認可コードの保存・取得・期限切れ |
| `oauth_repo.saveAccessToken` / `loadAccessToken` | アクセストークンの保存・取得 |
| `oauth_repo.cleanupExpiredTokens` | 期限切れトークン一括削除 |
| PIN認証ロジック | ロックアウト発動・解除の状態遷移 |

### Priority 5: リポジトリ層の個別テスト

ツール層テストで間接的にカバーされるが、リポジトリ層を直接テストすることで障害箇所の特定が容易になる。

| テスト対象 | 検証内容 |
|-----------|---------|
| `findOrCreateSession()` | 並行INSERT時のrace condition防止（FOR UPDATE） |
| `findOrCreateTags()` | ON CONFLICT DO NOTHINGの冪等性 |
| `linkMessageTags()` | 重複紐付けのON CONFLICT DO NOTHING |
| `searchMessages()` | 複合フィルタ条件のSQL生成 |
| `_getMessageTagsBatch()` | N+1防止のバッチ取得 |

## 7. カバレッジ方針

### 7.1 目標値

| レイヤー | 目標 | 備考 |
|---------|------|------|
| 純粋関数（encode/decode/validate/normalize） | 90%以上 | 分岐を網羅的にテスト |
| リポジトリ層 | 70%以上 | 主要なCRUD操作をカバー |
| ツール層 | 70%以上 | 正常系 + 主要エラーパスをカバー |
| OAuth（auth/） | 50%以上 | DB操作とPINロジックを優先 |
| server.py | 対象外 | FastMCPのエントリポイント。E2Eで担保 |

### 7.2 計測方法

```bash
uv run pytest --cov --cov-report=html --cov-report=term-missing
```

`htmlcov/` ディレクトリにカバレッジレポートが生成される。`.gitignore` に `htmlcov/` を追加すること。

### 7.3 カバレッジの扱い

- `fail_under` は初期値 `0` から段階的に引き上げる
- カバレッジ数値の追求よりも、Priority 1〜3のテストケースを確実に通すことを優先する
- 「カバレッジのためだけのテスト」は書かない

## 8. CI連携

### 8.1 GitHub Actions（将来）

Phase 1ではローカル実行のみ。GitHub Actions整備は晶葉（DevOps）の担当範囲で別途検討する。

**想定ワークフロー:**

```yaml
# .github/workflows/test.yml（設計イメージ）
name: Test
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:17
        env:
          POSTGRES_DB: lisanima_test_db
          POSTGRES_USER: lisa
          POSTGRES_PASSWORD: ${{ secrets.TEST_DB_PASSWORD }}
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Setup DB schema
        run: psql -f migrations/001_init.sql $DATABASE_URL
      - name: Run tests
        run: pytest --cov --cov-report=term-missing
```

**注意点:**

- PostgreSQL 17のservicesコンテナを使用し、実DBでテストする
- pg_trgm拡張は `001_init.sql` 内の `CREATE EXTENSION` で有効化される前提
- `.env` はCI環境ではGitHub Secretsから注入する

### 8.2 ローカル実行

```bash
# テスト用DB作成（初回のみ）
createdb -U lisa lisanima_test_db
psql -U lisa -d lisanima_test_db -f migrations/001_init.sql
psql -U lisa -d lisanima_test_db -f migrations/002_oauth.sql

# テスト実行
uv run pytest -v

# カバレッジ付き
uv run pytest --cov --cov-report=html
```

テスト用DBの接続情報は環境変数 `TEST_DB_NAME=lisanima_test_db` で切り替える。`db.py` の `get_dsn()` がデフォルトで `DB_NAME=lisanima_db` を参照するため、テスト用conftest.pyでは `monkeypatch.setenv("DB_NAME", "lisanima_test_db")` で上書きするか、テスト専用のDSN構築関数を用意する。

## 9. ディレクトリ構成

```
tests/
  conftest.py              # 共通fixture（db_conn, sample_session等）
  unit/
    test_emotion.py         # encodeEmotion / decodeEmotion
    test_tag_normalize.py   # normalizeTagName
    test_validate.py        # remember / recall のバリデーション
    test_pin_lockout.py     # PINロックアウト状態遷移
  integration/
    conftest.py             # 結合テスト用fixture（DB接続設定）
    test_remember.py        # remember ツール結合テスト
    test_recall.py          # recall ツール結合テスト
    test_session_repo.py    # セッションリポジトリ
    test_message_repo.py    # メッセージリポジトリ
    test_tag_repo.py        # タグリポジトリ
    test_oauth_repo.py      # OAuthリポジトリ
```

**命名規約:**

- テストファイル: `test_<対象モジュール名>.py`
- テスト関数: `test_<動作>_<条件>`（例: `test_encode_emotion_boundary_values`）
- fixture: スネークケース、用途が分かる名前（例: `sample_session`）
