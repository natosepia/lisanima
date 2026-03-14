# ログ戦略: lisanima

> セキュリティ観点の監査ログは [06_security.md](06_security.md) を参照。

## 1. 方針

- Python標準の `logging` モジュールを使用する
- MCPプロトコルが stdin/stdout を占有するため、ログは **stderr** に出力する
- systemd journal と連携し、永続化・検索・ローテーションを一元管理する
- 構造化ログ（JSON）は現時点では導入せず、人間可読フォーマットを採用する

## 2. ログレベル基準

| レベル | 用途 | 例 |
|--------|------|-----|
| DEBUG | 開発時のトレース情報。本番では無効 | SQL実行結果、セッション取得/作成の詳細 |
| INFO | 正常な業務イベント | サーバー起動/終了、MCPコマンド実行完了、OAuth認証成功、DBプール開始 |
| WARNING | 異常だが継続可能な状態 | PIN認証ロックアウト、期限切れトークンの掃除 |
| ERROR | 処理失敗。個別リクエストが完了できない | DB接続エラー、MCPコマンド実行失敗 |
| CRITICAL | システム全体が継続不能 | DBプール初期化失敗、設定ファイル欠損（現時点で該当箇所なし） |

**本番環境のデフォルトレベル: INFO**

DEBUGログはリポジトリ層で多用しているため、本番でDEBUGを有効にするとログ量が大幅に増加する。調査時のみ一時的に有効化すること。

## 3. 現在の実装

### 3.1 初期化（server.py）

```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
```

- エントリポイント `server.py` で一括設定
- 各モジュールは `logger = logging.getLogger(__name__)` で個別ロガーを取得

### 3.2 ログ出力箇所

| レイヤー | モジュール | ログ内容 |
|---------|-----------|---------|
| サーバー | server.py | 起動/終了、起動モード、OAuth有効化 |
| ツール | tools/remember.py, tools/recall.py | コマンド実行完了(INFO)、DB接続エラー(ERROR)、予期しない例外(ERROR) |
| リポジトリ | repositories/*.py | CRUD操作の詳細(DEBUG)、期限切れトークン掃除(INFO) |
| DB | db.py | プール開始/終了(INFO) |
| 認証 | auth/provider.py | クライアント登録、認可セッション作成、トークン交換/リフレッシュ/無効化(INFO) |
| 認証 | auth/pin.py | PIN認証失敗(WARNING, クライアントIP付き)、PIN認証ロックアウト(WARNING)、PIN認証成功(INFO) |

**PIN認証失敗のログフォーマット（fail2ban連携）:**

fail2banの `failregex` が `client=<HOST>` パターンでIPを抽出する前提（[06_security.md セクション10.3](06_security.md#103-アプリケーション側の対応) 参照）。
アプリケーション側は `X-Forwarded-For` ヘッダからクライアントIPを取得し、以下の形式で出力する。

```
2026-03-14 10:30:05,789 [lisanima.auth.pin] WARNING: PIN authentication failed: client=203.0.113.5, session_id=abc123
2026-03-14 10:30:35,012 [lisanima.auth.pin] WARNING: PIN認証ロックアウト発動: client=203.0.113.5, attempts=5
2026-03-14 10:31:00,345 [lisanima.auth.pin] INFO: PIN認証成功: client=203.0.113.5, session_id=abc123
```

- 失敗ログの `PIN authentication failed` は英語固定（fail2banのfailregexと一致させるため）
- `client=<IP>` はログメッセージの末尾ではなく、パースしやすい `key=value` 形式で埋め込む

**MCPコマンド実行ログのINFOレベル方針:**

セキュリティ監査の観点から「いつ誰が何のコマンドを叩いたか」を本番環境で追跡可能にするため、コマンド実行完了ログをDEBUGからINFOに引き上げる。
ただし、記憶内容（`content`）はログに出力しない（セクション7 マスキングルール参照）。

INFOレベルで出力する情報:
- コマンド名（`remember` / `recall`）
- パラメータのキー名（値は出力しない）
- 結果の識別子（`message_id` 等の数値ID）

```
2026-03-14 10:30:02,789 [lisanima.tools.remember] INFO: remember完了: message_id=42, keys=[content,speaker,emotion]
2026-03-14 10:30:03,012 [lisanima.tools.recall] INFO: recall完了: hits=3, keys=[keyword,speaker,limit]
```

## 4. ログフォーマット

### 4.1 現在のフォーマット

```
2026-03-14 10:30:00,123 [lisanima.server] INFO: lisanima MCPサーバー起動
2026-03-14 10:30:01,456 [lisanima.auth.provider] INFO: OAuthクライアント登録: abc123
```

**構成要素:**
- `%(asctime)s` — タイムスタンプ（ローカルタイム、ミリ秒付き）
- `[%(name)s]` — モジュール名（名前空間でフィルタ可能）
- `%(levelname)s` — ログレベル
- メッセージ本文

### 4.2 JSON構造化ログへの移行判断

現時点では人間可読フォーマットを維持する。理由:

- 個人運用のため、ログ集約基盤（ELK, Loki等）を運用していない
- `journalctl` の検索機能で十分なフィルタリングが可能
- 導入コストに対してメリットが薄い

JSON化の検討タイミング: ログ集約基盤を導入する場合、または複数インスタンス運用に移行する場合。

## 5. ログ出力先と永続化

### 5.1 出力経路

```
lisanima (stderr) → systemd journal → /var/log/journal/
```

- lisanimaプロセスはstderrにログを出力
- systemdが自動的にjournalに取り込む（`lisanima.service` 経由）
- ファイル出力（FileHandler等）は使用しない。journalに一元化する

### 5.2 ログの確認方法

```bash
# リアルタイム監視
journalctl -u lisanima.service -f

# 直近1時間のログ
journalctl -u lisanima.service --since "1 hour ago"

# ERRORレベル以上のみ
journalctl -u lisanima.service -p err

# 特定キーワードで検索
journalctl -u lisanima.service -g "PIN認証"
```

## 6. ログローテーション

systemd journalのデフォルト設定に準拠する。

| 設定項目 | デフォルト値 | 説明 |
|---------|------------|------|
| SystemMaxUse | ディスクの10% | journalの最大使用容量 |
| MaxRetentionSec | 0（無制限） | 保持期間 |
| MaxFileSec | 1month | ファイルローテーション間隔 |

lisanima単体のログ量は微量（1日数百行程度）のため、カスタム設定は不要。
必要に応じて `/etc/systemd/journald.conf` で調整可能。

## 7. 機密情報のマスキングルール

ログに以下の情報を **絶対に出力しない**:

| 分類 | 対象 | 理由 |
|------|------|------|
| 記憶内容 | `t_messages.content` の本文 | 会話履歴は高い機密性を持つ |
| 認証情報 | アクセストークン全文、リフレッシュトークン全文 | トークン漏洩によるなりすまし防止 |
| 認証情報 | PIN値、PINハッシュ | 認証バイパス防止 |
| 個人情報 | .envの接続文字列（パスワード含む） | DB不正アクセス防止 |

### 許容される出力

- トークンの **先頭8文字** のみ（例: `token[:8]` + `...`）— 現在の実装で対応済み
- client_id — 動的登録値であり秘密情報ではない
- セッションID、メッセージID — 数値IDのみ
- MCPコマンド名、パラメータのキー名（値は出力しない）

### 現在の実装状況

oauth_repo.py ではトークン値をスライスして出力している:

```python
logger.debug("アクセストークン発行: %s...", token[:8])
logger.debug("リフレッシュトークン発行: %s...", token[:8])
logger.debug("認可コード保存: %s...", code[:8])
```

remember/recall のツール層ではcontent本文をログに出力していない（適切）。

## 8. 今後の改善候補

| 項目 | 優先度 | 概要 |
|------|--------|------|
| リクエストID付与 | 中 | MCPリクエスト単位でtrace_idを付与し、一連のログを追跡可能にする。[06_security.md セクション11（異常検知）](06_security.md#11-ログ異常検知)の実装前提となる |
| ログレベルの動的変更 | 低 | 環境変数 `LOG_LEVEL` でランタイム切替。再起動なしで調査モードに移行 |
| 構造化ログ（JSON） | 低 | ログ集約基盤導入時に `python-json-logger` 等で移行 |
| パフォーマンスログ | 低 | DB操作の実行時間計測。スロークエリの検出 |

> **リクエストIDと異常検知の関係**: 06_security.md セクション11の異常検知（4xx/5xxスパイク、未知client_idからの大量リクエスト等）を実装する際、リクエストID（trace_id）が各ログ行に付与されていることが前提となる。リクエストIDにより、単一リクエストの認証→コマンド実行→DB操作の一連のログを横断的に追跡でき、異常パターンの特定精度が向上する。
