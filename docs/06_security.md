# セキュリティ設計: lisanima

> 認証プロトコルの実装詳細は [07_oauth.md](07_oauth.md) を参照。

## 1. セキュリティ方針

lisanimaは個人運用のAI人格記憶管理サーバーである。マルチテナントやパブリック公開は想定しない。

ただし、記憶データは会話履歴・感情・人格ルールなど**高い機密性**を持つ。
個人運用であっても以下の原則を遵守する。

- **最小権限**: DB接続ユーザーは専用ロール（`lisa`）に限定し、スーパーユーザー権限を使用しない
- **多層防御**: ネットワーク（TLS） + 認証（OAuth 2.1） + アプリケーション（バリデーション）の各層で保護
- **データ保全**: 物理削除を原則禁止し、論理削除（forget）で変更履歴を保持

---

# Part A: アプリケーションセキュリティ

## 2. 認証・認可

### 2.1 接続経路ごとの認証

| 接続経路 | 認証方式 | 根拠 |
|---------|---------|------|
| stdio（Claude Code） | なし | UNIXプロセス間通信。ローカルユーザー権限で保護される |
| Streamable HTTP（Desktop App等） | OAuth 2.1（PIN方式） | ネットワーク経由のためトークン認証が必須 |

### 2.2 OAuth 2.1概要

- **動的クライアント登録**（RFC 7591）: クライアントを事前登録なしで受け入れ
- **PKCE**（RFC 7636）: 認可コード横取り攻撃を防止（S256必須）
- **PIN認証**: パスワードレス。bcryptハッシュで検証
- **トークン有効期限**: アクセストークン1時間 / リフレッシュトークン30日
- **ブルートフォース対策**: 5回失敗で30秒ロックアウト（インメモリ管理）

実装詳細・フロー図・エンドポイント仕様は [07_oauth.md](07_oauth.md) に記載。

### 2.3 DCR（動的クライアント登録）の制限

動的クライアント登録（`/register`）は認証不要で誰でも叩ける仕様（RFC 7591準拠）。
以下の対策で悪用を抑制する。

| 対策 | 実施層 | 内容 |
|------|--------|------|
| レート制限 | nginx | `/register` に `limit_req` を設定（セクション8.1参照） |
| クライアント数上限 | アプリケーション | 登録済みクライアント数が閾値を超えた場合 `HTTP 503` を返却 |
| 期限切れクライアント削除 | 運用 | トークンが全て失効済みのクライアントを定期削除 |

## 3. 通信セキュリティ

### 3.1 HTTPS（Streamable HTTP経路）

```
Desktop App  --HTTPS-->  nginx (TLS終端)  --HTTP-->  lisanima (127.0.0.1:8765)
```

- **TLS終端**: nginxで実施。lisanimaプロセスはHTTPのみを扱う
- **証明書管理**: Let's Encrypt（certbot自動更新）
- **内部通信**: `127.0.0.1` バインドのため外部からの直接アクセス不可

### 3.2 stdio（ローカル経路）

- Claude Code / Gemini CLIからの接続はstdio（stdin/stdout）を使用
- ネットワークを経由しないため、暗号化・認証は不要
- UNIXプロセスのユーザー権限（`natosepia`）に依存

## 4. データ保護

### 4.1 DB接続情報の管理

- 接続情報（ホスト・ポート・ユーザー・パスワード・DB名）は `.env` ファイルで管理
- `.env` は `.gitignore` に登録し、リポジトリに含めない
- `OAUTH_PIN_HASH`（bcryptハッシュ）も `.env` に格納

### 4.2 論理削除によるデータ保全

- `t_messages.is_deleted` フラグによる論理削除（forgetコマンド）
- 削除時には `deleted_reason` に理由を記録し、追跡可能性を確保
- 物理削除は移行やり直し時の `TRUNCATE ... CASCADE` のみに限定
- ルールブック（`t_rulebooks`）はイミュータブル追記型。`is_retired` フラグで無効化し、変更履歴を保持

### 4.3 OAuthトークンの保管

- アクセストークン・リフレッシュトークンはDBに保管
- 各トークンに `expires_at` を設定し、有効期限切れトークンは認証時に拒否
- `revoke_token` でclient_id単位のAT/RT一括削除に対応（RFC 7009準拠）

## 5. 入力バリデーション

MCPコマンドのパラメータはInterface Layer（`tools/`）で検証する。

### 5.1 バリデーション方針

- **必須パラメータの空チェック**: `content`, `speaker` 等の空文字・空白のみを拒否
- **型・範囲チェック**: 感情値は `0 <= val <= 255` の整数、`limit >= 1`, `offset >= 0`
- **日付形式**: ISO 8601（`YYYY-MM-DD`）を `date.fromisoformat()` でパース。不正形式はエラー
- **許可キー検証**: 感情値の辞書キーを `{"joy", "anger", "sorrow", "fun"}` に限定
- **論理整合性**: `date_from > date_to` の逆転を検出

### 5.2 エラーレスポンス

バリデーションエラーは例外を投げず、構造化されたエラーレスポンスを返す。

```json
{"error": "INVALID_PARAMETER", "message": "content は空にできません"}
```

### 5.3 SQLインジェクション対策

- psycopg3のパラメータバインド（プレースホルダ `%s`）を使用
- 文字列結合によるSQL組み立ては行わない

### 5.4 HTMLインジェクション対策

- PIN認証画面のセッションIDは `html.escape()` でエスケープ
- ユーザー入力をHTMLに埋め込む箇所は全てエスケープ処理済み

## 6. 脅威モデル

個人運用における現実的な脅威と対策を整理する。

| 脅威 | リスク | 対策 |
|------|--------|------|
| ネットワーク盗聴 | 中 | nginx TLS終端によるHTTPS通信 |
| OAuth認可コード横取り | 中 | PKCE（S256）で防止 |
| PINブルートフォース | 中 | アプリ: 5回/30秒ロックアウト + nginx: rate limit + fail2ban連携 |
| トークン漏洩 | 中 | 有効期限（AT: 1h / RT: 30d） + revoke機能 |
| SQLインジェクション | 低 | psycopg3パラメータバインド |
| DB接続情報の漏洩 | 中 | .env管理 + .gitignore |
| 不正なMCPクライアント | 低 | OAuth DCR + トークン認証（HTTP経路のみ） |
| サーバー直接アクセス | 低 | lisanimaは127.0.0.1バインド。外部からの直接接続不可 |
| OAuthエンドポイントへのDoS | 中 | nginx rate limit + ファイアウォール（セクション8, 9参照） |
| DCR濫用（大量クライアント登録） | 中 | nginx rate limit + クライアント数上限（セクション2.3参照） |
| TLSダウングレード攻撃 | 低 | TLS 1.2以上強制 + HSTS（セクション8.2, 8.3参照） |

### 対象外（現時点で対策不要）

- **マルチテナント分離**: 単一ユーザー運用のため不要
- **WAF / IDS**: 個人運用規模では過剰。nginxのアクセスログ + fail2banで代替
- **トークン暗号化保管**: DB自体がローカルホスト接続限定のため、平文保管で許容

## 7. 監査・追跡可能性

### 7.1 現在の実装

- **アプリケーションログ**: Python `logging` → stderr → systemd journal
- **アクセス元記録**: `t_messages.source` にMCPクライアント識別子（`clientInfo.name`）を自動記録
- **OAuthイベント**: PIN認証成功/失敗、ロックアウト発動をログ出力
- **nginxアクセスログ**: HTTPリクエストの記録

### 7.2 今後の課題

- ログレベル方針の策定
- 構造化ログ（JSON形式）の検討
- OAuthトークンの期限切れレコード定期削除（クリーンアップジョブ）

詳細なログ設計は [08_logging.md](08_logging.md) を参照。

---

# Part B: インフラセキュリティ

> 実際の設定ファイルは各インフラコンポーネントの配置先（`/etc/nginx/`, `/etc/fail2ban/` 等）が正（SSOT）。
> 本セクションは設計意図と要件を記録する。設定例は参考として短く掲載する。

## 8. nginx硬化

### 8.1 レート制限（rate limiting）

OAuth/PINエンドポイントへのブルートフォース・DoSを抑制する。

| エンドポイント | zone名 | レート | burst | 目的 |
|---------------|--------|--------|-------|------|
| `/auth/pin` | `pin_limit` | 5r/m | 3 nodelay | PIN総当たり防止 |
| `/register` | `dcr_limit` | 10r/m | 5 nodelay | DCR濫用防止 |
| `/token` | `token_limit` | 30r/m | 10 nodelay | トークン取得の過剰リクエスト防止 |
| `/authorize` | `auth_limit` | 10r/m | 5 nodelay | 認可フロー濫用防止 |

設定例（httpブロック）:

```nginx
limit_req_zone $binary_remote_addr zone=pin_limit:10m rate=5r/m;
limit_req_zone $binary_remote_addr zone=dcr_limit:10m rate=10r/m;
```

設定例（locationブロック）:

```nginx
location = /auth/pin {
    limit_req zone=pin_limit burst=3 nodelay;
    # proxy_pass ...
}
```

**補足**: アプリ層のインメモリロックアウトはプロセス再起動でリセットされるため、nginx rate limitとの二重防御が必須。

### 8.2 TLS設定

TLS 1.2以上を強制し、弱い暗号スイートを排除する。

| 項目 | 設定値 |
|------|--------|
| プロトコル | TLSv1.2, TLSv1.3 |
| 暗号スイート | `ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM` |
| DHパラメータ | 2048bit以上（`ssl_dhparam`） |
| OCSP Stapling | 有効（`ssl_stapling on; ssl_stapling_verify on;`） |
| セッションチケット | 無効（Forward Secrecy確保: `ssl_session_tickets off;`） |

設定例:

```nginx
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers 'ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM';
ssl_prefer_server_ciphers on;
ssl_stapling on;
ssl_stapling_verify on;
ssl_session_tickets off;
```

### 8.3 HTTPセキュリティヘッダ

特にPIN認証画面（`/auth/pin`）はHTMLフォームを返すため、ヘッダ硬化が必要。

| ヘッダ | 値 | 目的 |
|--------|-----|------|
| `Strict-Transport-Security` | `max-age=315864000; includeSubDomains` | HTTPS強制（HSTS） |
| `X-Frame-Options` | `DENY` | クリックジャッキング防止 |
| `X-Content-Type-Options` | `nosniff` | MIMEスニッフィング防止 |
| `Content-Security-Policy` | `default-src 'none'; form-action 'self'; frame-ancestors 'none'` | CSP（PIN画面はフォーム送信のみ許可） |
| `Referrer-Policy` | `no-referrer` | リファラ漏洩防止 |
| `X-XSS-Protection` | `0` | ブラウザXSSフィルタ無効化（CSPで代替、誤検知回避） |

設定例（serverブロック共通）:

```nginx
add_header Strict-Transport-Security "max-age=315864000; includeSubDomains" always;
add_header X-Frame-Options "DENY" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "no-referrer" always;
```

設定例（PIN画面location）:

```nginx
location /auth/pin {
    add_header Content-Security-Policy "default-src 'none'; form-action 'self'; frame-ancestors 'none'" always;
    # 他のヘッダはserverブロックから継承されないため再指定が必要
}
```

> **注意**: nginxの `add_header` はlocationブロック内で1つでも指定すると、serverブロックの `add_header` が継承されなくなる。locationブロックでCSPを追加する場合は全ヘッダを再指定すること。

## 9. ファイアウォール

### 9.1 iptables / nftables ポリシー

デフォルトDROPポリシーで、必要なポートのみ許可する。

| 方向 | プロトコル | ポート | ソース | 許可理由 |
|------|----------|--------|--------|----------|
| INPUT | TCP | 22 | 管理者IPのみ | SSH |
| INPUT | TCP | 80 | ANY | HTTP → HTTPS リダイレクト |
| INPUT | TCP | 443 | ANY | HTTPS（nginx TLS終端） |
| INPUT | TCP | 5432 | 127.0.0.1 | PostgreSQL（ローカルのみ） |
| INPUT | - | - | lo | ループバック全許可 |
| INPUT | - | - | ESTABLISHED,RELATED | 既存接続の応答 |
| OUTPUT | - | - | ANY | 全許可（個人サーバー運用） |

設定例（ufw）:

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow from <管理者IP> to any port 22
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

### 9.2 PostgreSQL接続制限

DBへの接続はローカルホストに限定する。

| 設定箇所 | 内容 |
|----------|------|
| `postgresql.conf` | `listen_addresses = 'localhost'` |
| `pg_hba.conf` | `host lisanima_db lisa 127.0.0.1/32 scram-sha-256` |

- リモートからの5432ポートへの接続はファイアウォールで遮断（二重防御）
- 認証方式は `scram-sha-256`（`md5` は非推奨）

## 10. fail2ban連携

アプリケーションログからPIN認証失敗を検知し、IPレベルでバンする。

### 10.1 前提

- lisanimaのPIN認証失敗ログがsystemd journalに出力されること
- ログに送信元IPアドレスが含まれること（nginx `X-Forwarded-For` または `$remote_addr`）

### 10.2 設計

| 項目 | 値 |
|------|-----|
| filter名 | `lisanima-pin` |
| 検知パターン | PIN認証失敗ログの正規表現 |
| maxretry | 5 |
| findtime | 300（5分） |
| bantime | 86400（24時間） |
| action | iptables-multiport（port 443をDROP） |

設定例（filter）:

```ini
# /etc/fail2ban/filter.d/lisanima-pin.conf
[Definition]
failregex = PIN authentication failed.*client=<HOST>
ignoreregex =
```

設定例（jail）:

```ini
# /etc/fail2ban/jail.d/lisanima.conf
[lisanima-pin]
enabled  = true
filter   = lisanima-pin
backend  = systemd
journalmatch = _SYSTEMD_UNIT=lisanima.service
maxretry = 5
findtime = 300
bantime  = 86400
action   = iptables-multiport[name=lisanima, port="443", protocol=tcp]
```

### 10.3 アプリケーション側の対応

fail2banがIPを抽出できるよう、PIN認証失敗時のログ出力にクライアントIPを含める必要がある。

```
# 必要なログ形式の例
WARNING PIN authentication failed: client=203.0.113.5, session_id=abc123
```

- `X-Forwarded-For` ヘッダからクライアントIPを取得（nginx経由のため `request.headers` から抽出）
- nginxの `set_real_ip_from 127.0.0.1;` + `real_ip_header X-Forwarded-For;` でアプリ側に正しいIPを伝搬

## 11. ログ異常検知

### 11.1 検知対象

| 検知項目 | 条件 | 対応 |
|----------|------|------|
| PIN連続失敗 | 同一IPから5回/5分 | fail2banでIPバン（セクション10） |
| 4xx/5xxスパイク | 直近5分で閾値超過 | 通知（メール or Webhook） |
| 未知client_idからの大量リクエスト | 未登録client_idで短時間に複数回 | ログ警告 + 必要に応じ手動対応 |
| DCR大量登録 | 短時間にクライアント登録が閾値超過 | nginx rate limitで自動抑制 |

### 11.2 実装方針

- **Phase 1（現在）**: fail2banによるPIN失敗検知 + nginxアクセスログの目視確認
- **Phase 2以降**: 構造化ログ（JSON）導入後、ログ集約ツール（journalctl + スクリプト）で自動検知
- 通知先は個人運用のため、systemd journalのメール通知（`OnFailure=`）またはWebhookで十分

### 11.3 nginxログ形式の推奨

異常検知スクリプトが解析しやすいよう、JSON形式のアクセスログを推奨する。

```nginx
log_format json_combined escape=json
    '{"time":"$time_iso8601",'
    '"remote_addr":"$remote_addr",'
    '"request":"$request",'
    '"status":$status,'
    '"body_bytes_sent":$body_bytes_sent,'
    '"http_user_agent":"$http_user_agent"}';

access_log /var/log/nginx/lisanima_access.json json_combined;
```
