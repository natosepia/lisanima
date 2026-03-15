# インフラセキュリティ監査チェックシート: lisanima

> **目的**: [06_security.md](06_security.md) Part B（セクション8〜11）のインフラセキュリティ対策が日常運用で機能していることを定期検証する。
>
> **対象外**: アプリケーション層のセキュリティ（Part A）はコードレビューで対応するため本ドキュメントの範囲外。

## 1. 概要

| 項目 | 内容 |
|------|------|
| 対象 | nginx, TLS, ファイアウォール, fail2ban, PostgreSQL, ファイル権限 |
| 頻度 | 日次（cron自動）+ 月次（目視レビュー） |
| 自動チェック | `scripts/audit.sh` |
| ログ出力先 | `/var/log/lisanima/audit.log` |
| 関連ドキュメント | [06_security.md](06_security.md), [31_deployment.md](31_deployment.md), [32_operation.md](32_operation.md) |

## 2. チェック項目一覧

### 2.1 TLS / 証明書

| # | チェック項目 | 期待値 | 判定 | 根拠 |
|---|------------|--------|------|------|
| T-1 | SSL証明書の有効期限 | 残30日以上 | OK / WARN(残30日未満) / FAIL(残7日未満) | 06_security.md 8.2 |
| T-2 | TLSプロトコル | TLSv1.2, TLSv1.3 のみ有効 | OK / FAIL | 06_security.md 8.2 |
| T-3 | OCSP Stapling | 有効（`ssl_stapling on`） | OK / FAIL | 06_security.md 8.2 |
| T-4 | セッションチケット | 無効（`ssl_session_tickets off`） | OK / FAIL | 06_security.md 8.2 |
| T-5 | certbot timer | active | OK / FAIL | 31_deployment.md 6.1 |

### 2.2 nginx セキュリティヘッダ

| # | チェック項目 | 期待値 | 判定 | 根拠 |
|---|------------|--------|------|------|
| H-1 | Strict-Transport-Security | `max-age=315864000; includeSubDomains` | OK / FAIL | 06_security.md 8.3 |
| H-2 | X-Frame-Options | `DENY` | OK / FAIL | 06_security.md 8.3 |
| H-3 | X-Content-Type-Options | `nosniff` | OK / FAIL | 06_security.md 8.3 |
| H-4 | Referrer-Policy | `no-referrer` | OK / FAIL | 06_security.md 8.3 |
| H-5 | Content-Security-Policy（/auth/pin） | `default-src 'none'; form-action 'self'; frame-ancestors 'none'` | OK / FAIL | 06_security.md 8.3 |
| H-6 | X-XSS-Protection | `0` | OK / WARN | 06_security.md 8.3 |

### 2.3 nginx rate limit

| # | チェック項目 | 期待値 | 判定 | 根拠 |
|---|------------|--------|------|------|
| R-1 | pin_limit zone 定義 | `rate=5r/m` | OK / FAIL | 06_security.md 8.1 |
| R-2 | dcr_limit zone 定義 | `rate=10r/m` | OK / FAIL | 06_security.md 8.1 |
| R-3 | token_limit zone 定義 | `rate=30r/m` | OK / FAIL | 06_security.md 8.1 |
| R-4 | auth_limit zone 定義 | `rate=10r/m` | OK / FAIL | 06_security.md 8.1 |
| R-5 | /auth/pin に limit_req 適用 | zone=pin_limit | OK / FAIL | 06_security.md 8.1 |
| R-6 | /register に limit_req 適用 | zone=dcr_limit | OK / FAIL | 06_security.md 8.1 |

### 2.4 ファイアウォール（ufw）

| # | チェック項目 | 期待値 | 判定 | 根拠 |
|---|------------|--------|------|------|
| F-1 | ufw status | active | OK / FAIL | 06_security.md 9.1 |
| F-2 | デフォルトポリシー（incoming） | deny | OK / FAIL | 06_security.md 9.1 |
| F-3 | 許可ポート | 22（管理者IPのみ）, 80, 443 のみ | OK / FAIL | 06_security.md 9.1 |
| F-4 | 5432（PostgreSQL）が外部公開されていないこと | ルールなし or 127.0.0.1のみ | OK / FAIL | 06_security.md 9.1 |

### 2.5 PostgreSQL 接続制限

| # | チェック項目 | 期待値 | 判定 | 根拠 |
|---|------------|--------|------|------|
| P-1 | listen_addresses | `localhost` | OK / FAIL | 06_security.md 9.2 |
| P-2 | pg_hba.conf: lisa ロール | `127.0.0.1/32 scram-sha-256` | OK / FAIL | 06_security.md 9.2 |
| P-3 | 認証方式 | `scram-sha-256`（`md5` でない） | OK / FAIL | 06_security.md 9.2 |

### 2.6 fail2ban

| # | チェック項目 | 期待値 | 判定 | 根拠 |
|---|------------|--------|------|------|
| B-1 | fail2ban サービス状態 | active | OK / FAIL | 06_security.md 10 |
| B-2 | lisanima-pin jail | enabled, active | OK / FAIL | 06_security.md 10.2 |
| B-3 | maxretry | 5 | OK / WARN | 06_security.md 10.2 |
| B-4 | bantime | 86400（24時間） | OK / WARN | 06_security.md 10.2 |
| B-5 | filter 正規表現の有効性 | `fail2ban-regex` テスト成功 | OK / FAIL | 06_security.md 10.2 |

### 2.7 サービス稼働状態

| # | チェック項目 | 期待値 | 判定 | 根拠 |
|---|------------|--------|------|------|
| S-1 | lisanima.service | active (running) | OK / FAIL | 31_deployment.md 5 |
| S-2 | ポート 8765 リッスン | 127.0.0.1:8765 | OK / FAIL | 31_deployment.md 5 |
| S-3 | nginx | active (running) | OK / FAIL | 31_deployment.md 6 |
| S-4 | postgresql | active (running) | OK / FAIL | 31_deployment.md 2 |

### 2.8 ファイル権限

| # | チェック項目 | 期待値 | 判定 | 根拠 |
|---|------------|--------|------|------|
| D-1 | `.env` の権限 | 600（owner read/write のみ） | OK / FAIL | 06_security.md 4.1 |
| D-2 | `.env` の所有者 | lisanima実行ユーザー | OK / FAIL | 06_security.md 4.1 |
| D-3 | fail2ban filter/jail 権限 | 644, root:root | OK / WARN | - |
| D-4 | nginx設定ファイル権限 | 644, root:root | OK / WARN | - |

### 2.9 OAuth クリーンアップ

| # | チェック項目 | 期待値 | 判定 | 根拠 |
|---|------------|--------|------|------|
| O-1 | 期限切れトークン数 | 0件 | OK / WARN(1件以上) | 06_security.md 7.2 |
| O-2 | 全トークン失効済みクライアント数 | 0件 | OK / WARN(1件以上) | 06_security.md 2.3 |

## 3. 判定基準

| 判定 | 意味 | 対応 |
|------|------|------|
| **OK** | 期待値と一致。正常 | 対応不要 |
| **WARN** | 即座の問題はないが注意が必要 | 月次レビュー時に確認。改善を検討 |
| **FAIL** | セキュリティポリシー違反 | 是正フロー（セクション6）に従い即対応 |

WARNの具体例:
- 証明書残日数が30日未満（certbot自動更新で解消される可能性あり）
- fail2banのパラメータが設計値と異なる（意図的変更の可能性）
- 期限切れOAuthトークンが閾値超過（運用クリーンアップで解消）

## 4. 自動チェック（scripts/audit.sh）

### 4.1 実行方法

```bash
# 通常実行（全結果を表示）
sudo scripts/audit.sh

# 静粛モード（WARN/FAILのみ表示）
sudo scripts/audit.sh --quiet
```

### 4.2 cron 設定

```
# 毎日AM5:00にセキュリティ監査を実行
0 5 * * * /home/natosepia/project/lisanima/scripts/audit.sh --quiet 2>&1
```

crontab の初期設定手順は [31_deployment.md](31_deployment.md) セクション7を参照。

### 4.3 ログ出力先

| モード | 出力先 |
|--------|--------|
| 手動実行 | stdout + `/var/log/lisanima/audit.log`（append） |
| cron実行（--quiet） | `/var/log/lisanima/audit.log`（append）。WARN/FAILがある場合のみstdout |

### 4.4 ログローテーション

`/etc/logrotate.d/lisanima-audit` を以下の内容で作成する。

```
/var/log/lisanima/audit.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644 <user> <user>
}
```

- `<user>` は lisanima 実行ユーザーに置き換える
- 日次でローテーション、7世代保持、gzip圧縮
- `delaycompress`: 直近1世代は非圧縮（トラブルシュート時の即時参照用）
- `missingok`: ログファイルが存在しなくてもエラーにしない
- `notifempty`: 空ファイルはローテーションしない

ログディレクトリの初期作成手順は [31_deployment.md](31_deployment.md) セクション7.1を参照。

### 4.5 出力形式

```
========================================
 lisanima インフラセキュリティ監査
 実行日時: 2026-03-15 05:00:01
========================================

[2026-03-15 05:00:01] OK: [TLS/証明書有効期限] 証明書の残り有効期限: 58日
[2026-03-15 05:00:01] OK: [FW/ufw] ufw active
[2026-03-15 05:00:02] WARN: [OAuth/期限切れトークン] 期限切れトークン: 127件（定期削除を推奨）
[2026-03-15 05:00:02] FAIL: [ファイル権限/.env] .env パーミッションが 644（600であるべき）

=== 監査サマリ (2026-03-15 05:00:01) === OK: 18 / WARN: 1 / FAIL: 1 / Total: 20
========================================
```

`--quiet` オプション指定時はOK行を省略し、WARN/FAIL行とサマリのみを出力する。

## 5. 月次目視レビュー

自動チェックではカバーできない項目を月次で目視確認する。

### 5.1 レビュー項目

| # | レビュー項目 | 確認手順 | 着眼点 |
|---|------------|---------|--------|
| M-1 | fail2ban バンログの傾向 | `sudo fail2ban-client status lisanima-pin` + journal | 特定IPからの繰り返しバン、攻撃パターンの変化 |
| M-2 | nginx アクセスログの傾向 | `/var/log/nginx/lisanima_access.json` を確認 | 4xx/5xxの急増、未知のUser-Agent、異常なリクエストパターン |
| M-3 | OAuthクライアント登録状況 | `SELECT * FROM t_oauth_client ORDER BY created_at DESC` | 不審なクライアント登録がないか |
| M-4 | audit.log の WARN/FAIL 推移 | `/var/log/lisanima/audit.log` の直近30日分 | 同じ項目が繰り返しWARN/FAILしていないか |
| M-5 | ufw ログの確認 | `sudo grep -c "UFW BLOCK" /var/log/ufw.log` | ブロック件数の急増（スキャン・攻撃の兆候） |
| M-6 | TLS設定の陳腐化 | Mozilla SSL Configuration Generator 等で最新推奨値を確認 | 暗号スイートの非推奨化、新プロトコル対応 |

### 5.2 レビュー手順

1. `audit.log` の直近30日分から WARN/FAIL を抽出し、傾向を確認する
2. 上記 M-1〜M-6 を順に確認する
3. 是正が必要な場合はセクション6のフローに従う
4. レビュー結果をコミットログまたはissueに記録する

## 6. 是正フロー

### 6.1 FAIL 検出時の対応

```
FAIL検出 → 影響範囲の特定 → 即時是正 → 再チェック → 原因記録
```

1. **影響範囲の特定**: FAILの項目が他のセキュリティ対策に波及するか確認する
2. **即時是正**: 対応手順は [32_operation.md](32_operation.md) の該当セクションを参照する
   - サービス停止 → セクション2.1
   - 証明書期限切れ → セクション2.5
   - fail2ban関連 → セクション2.4
   - DB接続制限 → セクション2.6
3. **再チェック**: `scripts/audit.sh` を手動実行し、FAILが解消したことを確認する
4. **原因記録**: GitHub issueに `bug` ラベルで起票する（再発防止のため）

### 6.2 WARN 検出時の対応

- 月次レビュー時に確認し、改善が必要か判断する
- 3回連続で同じWARNが出ている場合は是正を実施する
- 意図的な設定変更の場合は、06_security.md の設計値を更新する

### 6.3 エスカレーション基準

| 状況 | 対応 |
|------|------|
| FAIL が1件でも検出 | なとせに即日報告 |
| 同一WARNが3回連続 | issueを起票し対応計画を立てる |
| fail2banのバンが急増 | nginx アクセスログと突合し、攻撃の有無を判断 |
| audit.sh 自体が実行失敗 | cron設定・スクリプト権限を確認し復旧する |
