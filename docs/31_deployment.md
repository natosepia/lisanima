# デプロイ手順: lisanima

ゼロからlisanimaを動かすまでの手順書。VPS障害時のリカバリ（RTO: 24時間）を実現するためのドキュメント。

> **SSOT注意**: 本ドキュメントはデプロイ手順に特化する。設計の「なぜ」は各設計ドキュメントを参照すること。

## 1. 前提条件

| コンポーネント | バージョン | 備考 |
|--------------|-----------|------|
| OS | Ubuntu 22.04+ | systemd必須 |
| Python | 3.12+ | `python3 --version` で確認 |
| PostgreSQL | 17.x | `psql --version` で確認 |
| nginx | 1.18+ | SSL終端・リバースプロキシ |
| certbot | 最新 | Let's Encrypt証明書取得 |
| uv | 最新 | Pythonパッケージ管理 |
| git | 最新 | リポジトリクローン |

## 2. PostgreSQL セットアップ

### 2.1 ロール作成

```bash
sudo -u postgres psql
```

```sql
CREATE ROLE lisa WITH LOGIN PASSWORD '<パスワード>';
```

### 2.2 データベース作成

```sql
CREATE DATABASE lisanima_db OWNER lisa ENCODING 'UTF8';
```

### 2.3 pg_trgm拡張の有効化

```bash
sudo -u postgres psql -d lisanima_db
```

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

### 2.4 DDL適用

[04_schema.md](04_schema.md) セクション7のDDLを適用する。

```bash
sudo -u postgres psql -d lisanima_db -f /path/to/lisanima/sql/ddl.sql
```

### 2.5 接続制限の確認

`pg_hba.conf` でlisaロールがローカルホストからのみ接続可能であることを確認する。

```
host lisanima_db lisa 127.0.0.1/32 scram-sha-256
```

詳細: [06_security.md](06_security.md) セクション9.2

## 3. ファイアウォール設定

### 3.1 ufw によるポート制御

デフォルトDROPポリシーで必要なポートのみ許可する。

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from <管理者IP> to any port 22
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

PostgreSQL（5432）はローカルホスト接続のみのためルール追加不要。

詳細: [06_security.md](06_security.md) セクション9

### 3.2 fail2ban 設定

PIN認証失敗を検知してIPをバンするfail2ban設定を配置する。

1. filterファイルを作成する
   ```ini
   # /etc/fail2ban/filter.d/lisanima-pin.conf
   [Definition]
   failregex = PIN authentication failed.*client=<HOST>
   ignoreregex =
   ```

2. jailファイルを作成する
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

3. fail2banを再起動する
   ```bash
   sudo systemctl restart fail2ban
   ```

4. jail が有効になっていることを確認する
   ```bash
   sudo fail2ban-client status lisanima-pin
   ```

詳細: [06_security.md](06_security.md) セクション10

## 4. アプリケーション セットアップ

### 3.1 リポジトリクローン

```bash
git clone <リポジトリURL> /home/<user>/project/lisanima
```

### 3.2 依存関係インストール

```bash
cd /home/<user>/project/lisanima
uv sync
```

### 3.3 .env 設定

プロジェクトルートに `.env` を作成し、以下の環境変数を設定する。

| 変数名 | 説明 |
|--------|------|
| `DB_HOST` | PostgreSQL接続先（通常 `localhost`） |
| `DB_PORT` | PostgreSQLポート（通常 `5432`） |
| `DB_NAME` | データベース名（`lisanima_db`） |
| `DB_USER` | DBロール名（`lisa`） |
| `DB_PASSWORD` | DBロールのパスワード |
| `OAUTH_PIN_HASH` | PIN認証用bcryptハッシュ |

PINハッシュの生成:

```bash
python3 -c "import bcrypt; print(bcrypt.hashpw(b'<your-pin>', bcrypt.gensalt()).decode())"
```

詳細: [07_oauth.md](07_oauth.md) セクション3, 10

### 3.4 stdioモードでの動作確認

```bash
uv run lisanima
```

MCPプロトコルの応答（JSON-RPC）が返ることを確認する。`Ctrl+C` で終了。

## 5. systemd サービス設定

### 4.1 ユニットファイルの作成

`/etc/systemd/system/lisanima.service` を以下の内容で作成する。

```ini
[Unit]
Description=lisanima MCP Server
After=network.target postgresql.service

[Service]
Type=simple
User=<user>
WorkingDirectory=/home/<user>/project/lisanima
ExecStart=/home/<user>/project/lisanima/.venv/bin/lisanima --http
Restart=on-failure
RestartSec=5
Environment=PATH=/home/<user>/project/lisanima/.venv/bin:/usr/bin

[Install]
WantedBy=multi-user.target
```

- `<user>` は実行ユーザーに置き換える
- `--http` でStreamable HTTPモード起動（ポート: 8765）
- ログはstderr → systemd journal に自動収集される（[08_logging.md](08_logging.md) セクション5参照）

### 4.2 有効化・起動

```bash
sudo systemctl daemon-reload
sudo systemctl enable lisanima.service
sudo systemctl start lisanima.service
```

### 4.3 状態確認

```bash
sudo systemctl status lisanima.service
```

`active (running)` であることを確認する。

## 6. nginx 設定

### 5.1 SSL証明書の取得

```bash
sudo certbot certonly --nginx -d <your-domain>
```

### 5.2 lisanima用のnginx設定

`/etc/nginx/sites-available/<your-domain>` のserverブロック内に以下を追加する。

#### rate limit zone定義（httpブロック）

```nginx
# /etc/nginx/nginx.conf の http ブロック内
limit_req_zone $binary_remote_addr zone=pin_limit:10m rate=5r/m;
limit_req_zone $binary_remote_addr zone=dcr_limit:10m rate=10r/m;
limit_req_zone $binary_remote_addr zone=token_limit:10m rate=30r/m;
limit_req_zone $binary_remote_addr zone=auth_limit:10m rate=10r/m;
```

詳細: [06_security.md](06_security.md) セクション8.1

#### location設定（serverブロック）

```nginx
# --- セキュリティヘッダ（serverブロック共通） ---
add_header Strict-Transport-Security "max-age=315864000; includeSubDomains" always;
add_header X-Frame-Options "DENY" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "no-referrer" always;

# --- lisanima MCP本体 ---
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

# --- RFC 9728 Protected Resource Metadata ---
location /.well-known/oauth-protected-resource/lisanima/ {
    proxy_pass http://127.0.0.1:8765/.well-known/oauth-protected-resource/;
    proxy_set_header Host 127.0.0.1:8765;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# --- RFC 8414 Authorization Server Metadata ---
location = /.well-known/oauth-authorization-server {
    proxy_pass http://127.0.0.1:8765/.well-known/oauth-authorization-server;
    proxy_set_header Host 127.0.0.1:8765;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# --- 3/26 auth spec fallback: OAuthエンドポイント（ルートドメイン配置） ---
location = /authorize {
    limit_req zone=auth_limit burst=5 nodelay;
    proxy_pass http://127.0.0.1:8765/authorize;
    proxy_set_header Host 127.0.0.1:8765;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location = /token {
    limit_req zone=token_limit burst=10 nodelay;
    proxy_pass http://127.0.0.1:8765/token;
    proxy_set_header Host 127.0.0.1:8765;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location = /register {
    limit_req zone=dcr_limit burst=5 nodelay;
    proxy_pass http://127.0.0.1:8765/register;
    proxy_set_header Host 127.0.0.1:8765;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# --- PIN認証画面 ---
location /auth/pin {
    limit_req zone=pin_limit burst=3 nodelay;
    proxy_pass http://127.0.0.1:8765/auth/pin;
    proxy_set_header Host 127.0.0.1:8765;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # CSP + 全セキュリティヘッダ再指定（nginxのadd_header継承が切れるため）
    add_header Strict-Transport-Security "max-age=315864000; includeSubDomains" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "no-referrer" always;
    add_header Content-Security-Policy "default-src 'none'; form-action 'self'; frame-ancestors 'none'" always;
}
```

#### TLS設定（serverブロック）

```nginx
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers 'ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM';
ssl_prefer_server_ciphers on;
ssl_stapling on;
ssl_stapling_verify on;
ssl_session_tickets off;
```

詳細: [06_security.md](06_security.md) セクション8.2, 8.3

#### JSONアクセスログ（推奨）

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

詳細: [06_security.md](06_security.md) セクション11.3

### 5.3 設定反映

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### 5.4 重要な注意事項

- 全てのlisanima向けlocationで `proxy_set_header Host 127.0.0.1:8765;` が必須
- 3/26 auth specの制約により、OAuthエンドポイント（`/authorize`, `/token`, `/register`）はルートドメインに配置が必要（[07_oauth.md](07_oauth.md) セクション8参照）
- `add_header` はlocationブロック内で1つでも指定すると、serverブロックの `add_header` が継承されなくなる。PIN画面のlocationでは全ヘッダを再指定すること

## 7. バックアップ・cron 初期設定

### 7.1 バックアップディレクトリの作成

```bash
mkdir -p ~/backup
```

### 7.2 crontab 登録

```bash
crontab -e
```

以下を追記する:

```
# 毎日AM3:00にlisanima_dbバックアップ取得
0 3 * * * pg_dump -h localhost -U lisa lisanima_db > ~/backup/lisanima_db_$(date +\%Y\%m\%d).sql

# 毎週日曜AM4:00に30日超のバックアップを削除
0 4 * * 0 find ~/backup -name "lisanima_db_*.sql" -mtime +30 -delete
```

運用時のバックアップ確認・リストア手順は [32_operation.md](32_operation.md) を参照。

## 8. Claude Code 側の設定

ユーザーレベル（プロジェクト横断）でMCPサーバーを登録する。

```bash
claude mcp add --scope user lisanima -- uv run --directory /home/<user>/project/lisanima python -m lisanima.server
```

stdioモード（ローカルサブプロセス通信）で接続される。認証は不要。

## 9. Desktop App 側の設定

1. Claude Desktop App を開く
2. 設定 > コネクタ > 「カスタムコネクタを追加」
3. MCPサーバーURLに `https://<your-domain>/lisanima/mcp` を入力
4. OAuth認証フロー（ブラウザでPIN入力）を完了して接続

## 10. 動作確認チェックリスト

| # | 確認項目 | 確認コマンド / 方法 | 期待結果 |
|---|---------|-------------------|---------|
| 1 | PostgreSQL稼働 | `sudo systemctl status postgresql` | active (running) |
| 2 | lisanima_db接続 | `psql -h localhost -U lisa -d lisanima_db -c '\dt'` | テーブル一覧が表示される |
| 3 | pg_trgm有効 | `psql -d lisanima_db -c "SELECT * FROM pg_extension WHERE extname='pg_trgm'"` | 1行返却 |
| 4 | ファイアウォール | `sudo ufw status` | Status: active、22/80/443のみ許可 |
| 5 | fail2ban | `sudo fail2ban-client status lisanima-pin` | jail が active |
| 6 | lisanima.service稼働 | `sudo systemctl status lisanima.service` | active (running) |
| 7 | ポート8765リッスン | `ss -tlnp \| grep 8765` | 127.0.0.1:8765 が表示される |
| 8 | nginx設定テスト | `sudo nginx -t` | test is successful |
| 9 | HTTPS接続 | `curl -I https://<your-domain>/lisanima/mcp` | 401 Unauthorized（OAuth未認証のため） |
| 10 | ASメタデータ | `curl https://<your-domain>/.well-known/oauth-authorization-server` | JSON応答（issuer, authorize等のURL） |
| 11 | SSL証明書 | `sudo certbot certificates` | 有効期限が表示される |
| 12 | Claude Code MCP | Claude Code で `recall` を実行 | 結果が返る |
| 13 | Desktop App MCP | Desktop App でカスタムコネクタ接続 | PIN認証後にMCP接続成功 |
| 14 | journalログ | `journalctl -u lisanima.service --since "5 min ago"` | 起動ログが表示される |
