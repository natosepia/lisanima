# オペレーションドキュメント: lisanima

運用者なとせのためのランブック。「脳がSPOF」を解消する。

## 1. 定型業務

### 1.1 pg_dump バックアップ確認

バックアップはcronで自動実行される前提（初期設定は [31_deployment.md](31_deployment.md) セクション7参照）。手動実行・確認手順:

```bash
# バックアップの手動実行
pg_dump -h localhost -U lisa lisanima_db > ~/backup/lisanima_db_$(date +%Y%m%d).sql

# 最新バックアップの確認
ls -lt ~/backup/lisanima_db_*.sql | head -5
```

**確認頻度**: 週1回（バックアップファイルが生成されているか・サイズが妥当か）

### 1.2 OAuthトークン掃除

期限切れのOAuthレコードを削除する。放置するとテーブルが肥大化する。

```bash
psql -h localhost -U lisa -d lisanima_db
```

```sql
DELETE FROM t_oauth_auth_session WHERE expires_at < NOW();
DELETE FROM t_oauth_auth_code WHERE expires_at < NOW();
DELETE FROM t_oauth_access_token WHERE expires_at < NOW();
DELETE FROM t_oauth_refresh_token WHERE expires_at < NOW();
```

詳細: [07_oauth.md](07_oauth.md) セクション5

**実施頻度**: 月1回程度。トークンの蓄積量に応じて判断。

### 1.3 certbot 証明書更新確認

Let's Encrypt証明書はcertbotのcron/timerで自動更新される。

```bash
# 証明書の有効期限を確認
sudo certbot certificates

# certbot timerの状態を確認
sudo systemctl status certbot.timer

# 自動更新のドライラン
sudo certbot renew --dry-run
```

**確認頻度**: 月1回。有効期限が30日以内の場合は手動更新を検討（セクション2.5参照）。

### 1.4 systemd サービス状態確認

```bash
# lisanimaサービスの状態
sudo systemctl status lisanima.service

# PostgreSQLの状態
sudo systemctl status postgresql

# nginxの状態
sudo systemctl status nginx
```

**確認頻度**: 週1回、または障害報告時。

### 1.5 journalctl でのログ確認

```bash
# 直近1日のログ（ERRORレベル以上）
journalctl -u lisanima.service --since "1 day ago" -p err

# 直近1日のログ（全レベル）
journalctl -u lisanima.service --since "1 day ago"

# PIN認証関連のログ
journalctl -u lisanima.service -g "PIN"

# リアルタイム監視
journalctl -u lisanima.service -f
```

ログ設計の詳細: [08_logging.md](08_logging.md)

**確認頻度**: 週1回。ERRORログの有無を確認する。

## 2. 非定型業務

### 2.1 プロセス復旧（lisanima.service が落ちた場合）

**症状**: Desktop Appから接続できない、Claude Codeのremember/recallが失敗する。

1. サービス状態を確認する
   ```bash
   sudo systemctl status lisanima.service
   ```

2. 直近のログでエラー原因を確認する
   ```bash
   journalctl -u lisanima.service --since "30 min ago" --no-pager
   ```

3. サービスを再起動する
   ```bash
   sudo systemctl restart lisanima.service
   ```

4. 状態が `active (running)` になっていることを確認する
   ```bash
   sudo systemctl status lisanima.service
   ```

5. ポート8765でリッスンしていることを確認する
   ```bash
   ss -tlnp | grep 8765
   ```

**注意**: `Restart=on-failure` が設定されているため、一時的な障害は自動復旧する。手動復旧が必要なのは設定ミスやDB接続障害など根本原因がある場合。

### 2.2 DBマイグレーション実行

スキーマ変更時の手順。詳細な戦略は [05_schema_migration.md](05_schema_migration.md) を参照。

1. サービスを停止する
   ```bash
   sudo systemctl stop lisanima.service
   ```

2. バックアップを取得する
   ```bash
   pg_dump -h localhost -U lisa lisanima_db > ~/backup/lisanima_db_pre_migration_$(date +%Y%m%d).sql
   ```

3. [04_schema.md](04_schema.md) セクション7のDDLを理想形に編集する

4. マイグレーションユーティリティを実行する（退避 → DROP → CREATE → データ移行）
   - 手順の詳細は [05_schema_migration.md](05_schema_migration.md) セクション3を参照

5. 動作確認する
   ```bash
   psql -h localhost -U lisa -d lisanima_db -c '\dt'
   ```

6. サービスを再開する
   ```bash
   sudo systemctl start lisanima.service
   ```

7. `_work` テーブルは動作確認が完了してから手動で削除する

### 2.3 PIN変更手順

1. 新しいPINのbcryptハッシュを生成する
   ```bash
   python3 -c "import bcrypt; print(bcrypt.hashpw(b'<new-pin>', bcrypt.gensalt()).decode())"
   ```

2. `.env` の `OAUTH_PIN_HASH` を更新する
   ```
   OAUTH_PIN_HASH=<生成したハッシュ>
   ```

3. サービスを再起動する
   ```bash
   sudo systemctl restart lisanima.service
   ```

4. Desktop Appで再認証して動作確認する（既存トークンは有効期限まで使用可能）

### 2.4 fail2ban 誤BAN解除

**症状**: 正当なIPからDesktop Appが接続できなくなった。

1. BANされたIPを確認する
   ```bash
   sudo fail2ban-client status lisanima-pin
   ```

2. 対象IPのBAN解除する
   ```bash
   sudo fail2ban-client set lisanima-pin unbanip <IPアドレス>
   ```

3. 正常に接続できることを確認する

fail2ban設定の詳細: [06_security.md](06_security.md) セクション10

### 2.5 SSL証明書手動更新

**症状**: certbot自動更新が失敗し、証明書が期限切れに近づいている。

1. 証明書の状態を確認する
   ```bash
   sudo certbot certificates
   ```

2. 更新を試行する
   ```bash
   sudo certbot renew
   ```

3. 更新が失敗する場合、証明書を再取得する
   ```bash
   sudo certbot certonly --nginx -d <your-domain>
   ```

4. nginxをリロードする
   ```bash
   sudo systemctl reload nginx
   ```

5. HTTPS接続を確認する
   ```bash
   curl -I https://<your-domain>/lisanima/mcp
   ```

### 2.6 PostgreSQL接続トラブルシューティング

**症状**: lisanimaのログに `DB接続エラー` が出力される。

1. PostgreSQLの稼働状態を確認する
   ```bash
   sudo systemctl status postgresql
   ```

2. PostgreSQLが停止している場合は起動する
   ```bash
   sudo systemctl start postgresql
   ```

3. lisaロールで接続できるか確認する
   ```bash
   psql -h localhost -U lisa -d lisanima_db -c 'SELECT 1'
   ```

4. 接続できない場合、pg_hba.confを確認する
   ```bash
   sudo cat /etc/postgresql/17/main/pg_hba.conf | grep lisa
   ```
   `host lisanima_db lisa 127.0.0.1/32 scram-sha-256` の行があることを確認する。

5. PostgreSQLのログを確認する
   ```bash
   sudo journalctl -u postgresql --since "30 min ago"
   ```

6. 問題解決後、lisanimaを再起動する
   ```bash
   sudo systemctl restart lisanima.service
   ```

## 3. バックアップ/リストア

### 3.1 バックアップ手順（pg_dump）

```bash
pg_dump -h localhost -U lisa lisanima_db > ~/backup/lisanima_db_$(date +%Y%m%d).sql
```

- 出力形式: プレーンSQL（可読性重視）
- OAuthトークンテーブルも含まれるが、リストア後は期限切れで自然失効する

### 3.2 リストア手順（pg_restore）

1. サービスを停止する
   ```bash
   sudo systemctl stop lisanima.service
   ```

2. 既存データベースを削除・再作成する
   ```bash
   sudo -u postgres psql -c "DROP DATABASE lisanima_db;"
   sudo -u postgres psql -c "CREATE DATABASE lisanima_db OWNER lisa ENCODING 'UTF8';"
   ```

3. pg_trgm拡張を有効化する
   ```bash
   sudo -u postgres psql -d lisanima_db -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
   ```

4. バックアップからリストアする
   ```bash
   psql -h localhost -U lisa -d lisanima_db < ~/backup/lisanima_db_YYYYMMDD.sql
   ```

5. テーブルが正しく復元されたか確認する
   ```bash
   psql -h localhost -U lisa -d lisanima_db -c '\dt'
   ```

6. サービスを再開する
   ```bash
   sudo systemctl start lisanima.service
   ```

### 3.3 バックアップの保管場所・ローテーション方針

| 項目 | 方針 |
|------|------|
| 保管場所 | `~/backup/` |
| ファイル名 | `lisanima_db_YYYYMMDD.sql` |
| 保持期間 | 直近30日分 |
| ローテーション | 30日超のファイルを手動削除、またはcronで自動削除 |
| 外部バックアップ | 必要に応じてオブジェクトストレージ等に転送（現時点では未実施） |

crontabの初期設定は [31_deployment.md](31_deployment.md) セクション7を参照。

## 4. 監視項目一覧

| # | 監視対象 | 確認方法 | 異常の判断基準 |
|---|---------|---------|--------------|
| 1 | lisanima.service | `systemctl status lisanima.service` | `active (running)` でない |
| 2 | PostgreSQL | `systemctl status postgresql` | `active (running)` でない |
| 3 | nginx | `systemctl status nginx` | `active (running)` でない |
| 4 | ポート8765 | `ss -tlnp \| grep 8765` | リッスンしていない |
| 5 | SSL証明書有効期限 | `sudo certbot certificates` | 残り30日以内 |
| 6 | ディスク使用量 | `df -h` | 使用率80%超 |
| 7 | journalエラーログ | `journalctl -u lisanima.service -p err --since "1 day ago"` | ERRORログが出力されている |
| 8 | PIN認証失敗 | `journalctl -u lisanima.service -g "PIN authentication failed"` | 短時間に大量の失敗（攻撃の兆候） |
| 9 | fail2ban状態 | `sudo fail2ban-client status lisanima-pin` | 意図しないIPがBANされている |
| 10 | バックアップ | `ls -lt ~/backup/lisanima_db_*.sql \| head -1` | 直近のバックアップが存在しない |
| 11 | DB接続 | `psql -h localhost -U lisa -d lisanima_db -c 'SELECT 1'` | 接続エラー |
| 12 | OAuthトークン蓄積 | `psql -d lisanima_db -c "SELECT COUNT(*) FROM t_oauth_access_token WHERE expires_at < NOW()"` | 期限切れトークンが大量に残存 |
