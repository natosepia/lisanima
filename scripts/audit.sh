#!/usr/bin/env bash
#
# lisanima インフラセキュリティ監査スクリプト
# 06_security.md Part B（セクション8〜11）の運用チェックを自動実行する
# cron日次実行を想定。sudo権限で実行すること。
#
# Usage:
#   sudo bash ~/project/lisanima/scripts/audit.sh [--quiet]
#
# --quiet: WARN/FAILがある場合のみ詳細出力（cron向け）

# =============================================================================
# 設定（/etc/lisanima/audit.conf で上書き可能）
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONF_FILE="${SCRIPT_DIR}/audit.conf"
if [[ -f "$CONF_FILE" ]]; then
    # shellcheck source=./audit.conf
    source "$CONF_FILE"
fi

# conf未定義時のデフォルト値
DOMAIN="${DOMAIN:-FQDN}"
PROJECT_DIR="${PROJECT_DIR:-/home/natosepia/project/lisanima}"
DB_NAME="${DB_NAME:-db_name}"
DB_USER="${DB_ROLE:-${DB_USER:-user_name}}"
LOG_DIR="${LOG_DIR:-/var/log/lisanima}"
LISANIMA_PORT="${LISANIMA_PORT:-8080}"
FAIL2BAN_MAXRETRY="${FAIL2BAN_MAXRETRY:-5}"
FAIL2BAN_BANTIME="${FAIL2BAN_BANTIME:-86400}"

LOG_FILE="${LOG_DIR}/audit.log"
ENV_FILE="${PROJECT_DIR}/.env"

QUIET=false
[[ "${1:-}" == "--quiet" ]] && QUIET=true

# カウンタ
COUNT_OK=0
COUNT_WARN=0
COUNT_FAIL=0

# 結果蓄積用
RESULTS=()

# =============================================================================
# ユーティリティ関数
# =============================================================================

# ログディレクトリ作成
mkdir -p "${LOG_DIR}" 2>/dev/null || true

# 結果記録関数
record() {
    local level="$1"  # OK / WARN / FAIL
    local category="$2"
    local message="$3"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    case "$level" in
        OK)   COUNT_OK=$((COUNT_OK + 1)) ;;
        WARN) COUNT_WARN=$((COUNT_WARN + 1)) ;;
        FAIL) COUNT_FAIL=$((COUNT_FAIL + 1)) ;;
    esac

    local line="[${timestamp}] ${level}: [${category}] ${message}"
    RESULTS+=("$line")
}

# =============================================================================
# チェック関数
# =============================================================================

# ---------------------------------------------------------------------------
# TLS / 証明書
# ---------------------------------------------------------------------------
check_tls_cert_expiry() {
    local category="TLS/証明書有効期限"
    local expiry_date
    expiry_date=$(echo | openssl s_client -servername "${DOMAIN}" -connect "${DOMAIN}:443" 2>/dev/null \
        | openssl x509 -noout -enddate 2>/dev/null | sed 's/notAfter=//')

    if [[ -z "$expiry_date" ]]; then
        record "FAIL" "$category" "証明書情報を取得できません"
        return
    fi

    local expiry_epoch
    expiry_epoch=$(date -d "$expiry_date" +%s 2>/dev/null)
    local now_epoch
    now_epoch=$(date +%s)
    local days_left=$(( (expiry_epoch - now_epoch) / 86400 ))

    if [[ $days_left -lt 0 ]]; then
        record "FAIL" "$category" "証明書は期限切れです（${expiry_date}）"
    elif [[ $days_left -lt 7 ]]; then
        record "FAIL" "$category" "証明書の残り有効期限: ${days_left}日（7日未満は即対応）"
    elif [[ $days_left -lt 30 ]]; then
        record "WARN" "$category" "証明書の残り有効期限: ${days_left}日（${expiry_date}）"
    else
        record "OK" "$category" "証明書の残り有効期限: ${days_left}日"
    fi
}

check_tls_protocol() {
    local category="TLS/プロトコル"
    local fail_found=false

    # TLS 1.0, 1.1 が無効であることを確認
    for proto in tls1 tls1_1; do
        local result
        result=$(echo | openssl s_client -"${proto}" -connect "${DOMAIN}:443" 2>&1)
        if echo "$result" | grep -q "BEGIN CERTIFICATE"; then
            record "FAIL" "$category" "非推奨プロトコル ${proto} が有効です"
            fail_found=true
        fi
    done

    # TLS 1.2, 1.3 が有効であることを確認
    for proto in tls1_2 tls1_3; do
        local result
        result=$(echo | openssl s_client -"${proto}" -connect "${DOMAIN}:443" 2>&1)
        if ! echo "$result" | grep -q "BEGIN CERTIFICATE"; then
            record "FAIL" "$category" "${proto} が無効です"
            fail_found=true
        fi
    done

    if [[ "$fail_found" == false ]]; then
        record "OK" "$category" "TLS 1.2/1.3のみ許可"
    fi
}

check_ocsp_stapling() {
    local category="TLS/OCSP Stapling"
    local result
    result=$(echo | openssl s_client -servername "${DOMAIN}" -connect "${DOMAIN}:443" -status 2>/dev/null)

    if echo "$result" | grep -q "OCSP Response Status: successful"; then
        record "OK" "$category" "OCSP Stapling有効"
    else
        record "WARN" "$category" "OCSPレスポンスが取得できません（初回アクセスやキャッシュ未生成の可能性あり）"
    fi
}

check_tls_session_tickets() {
    local category="TLS/Session Tickets"
    local nginx_conf_dir="/etc/nginx"

    if grep -rq "ssl_session_tickets\s*off" "${nginx_conf_dir}/" 2>/dev/null; then
        record "OK" "$category" "ssl_session_tickets off 設定済み"
    else
        record "WARN" "$category" "ssl_session_tickets off が設定されていません"
    fi
}

check_certbot_timer() {
    local category="TLS/certbot timer"

    if systemctl is-active --quiet certbot.timer 2>/dev/null; then
        record "OK" "$category" "certbot.timer active"
    else
        record "FAIL" "$category" "certbot.timerが停止しています"
    fi
}

# ---------------------------------------------------------------------------
# nginxセキュリティヘッダ
# ---------------------------------------------------------------------------
check_security_headers() {
    local category="nginx/セキュリティヘッダ"
    local headers
    headers=$(curl -sI "https://${DOMAIN}/lisanima/" 2>/dev/null)

    if [[ -z "$headers" ]]; then
        record "FAIL" "$category" "HTTPレスポンスを取得できません"
        return
    fi

    # 共通ヘッダのチェック
    local -A expected_headers=(
        ["Strict-Transport-Security"]="max-age="
        ["X-Frame-Options"]="DENY"
        ["X-Content-Type-Options"]="nosniff"
        ["Referrer-Policy"]="no-referrer"
    )

    for header in "${!expected_headers[@]}"; do
        local pattern="${expected_headers[$header]}"
        if echo "$headers" | grep -qi "${header}.*${pattern}"; then
            record "OK" "$category" "${header} 設定済み"
        else
            record "FAIL" "$category" "${header} が未設定または値が不正"
        fi
    done
}

check_csp_pin_page() {
    local category="nginx/CSP(PIN画面)"
    local headers
    headers=$(curl -sI "https://${DOMAIN}/auth/pin" 2>/dev/null)

    if echo "$headers" | grep -qi "Content-Security-Policy"; then
        record "OK" "$category" "Content-Security-Policy 設定済み"
    else
        record "FAIL" "$category" "/auth/pin に Content-Security-Policy が未設定"
    fi
}

check_xss_protection() {
    local category="nginx/X-XSS-Protection"
    local headers
    headers=$(curl -sI "https://${DOMAIN}/lisanima/" 2>/dev/null)

    if [[ -z "$headers" ]]; then
        record "WARN" "$category" "HTTPレスポンスを取得できません"
        return
    fi

    if echo "$headers" | grep -qi "X-XSS-Protection.*0"; then
        record "OK" "$category" "X-XSS-Protection: 0 設定済み"
    else
        record "WARN" "$category" "X-XSS-Protection: 0 が未設定（モダンブラウザでは非推奨ヘッダだが設定推奨）"
    fi
}

# ---------------------------------------------------------------------------
# nginx rate limit
# ---------------------------------------------------------------------------
check_nginx_rate_limit() {
    local category="nginx/rate limit"
    local nginx_conf_dir="/etc/nginx"

    local required_zones=("pin_limit" "dcr_limit" "token_limit" "auth_limit")
    local missing=()

    for zone in "${required_zones[@]}"; do
        if grep -rq "limit_req_zone.*zone=${zone}" "${nginx_conf_dir}/" 2>/dev/null; then
            record "OK" "$category" "zone=${zone} 定義あり"
        else
            record "FAIL" "$category" "zone=${zone} が未定義"
            missing+=("$zone")
        fi
    done
}

# ---------------------------------------------------------------------------
# ファイアウォール (ufw)
# ---------------------------------------------------------------------------
check_firewall() {
    local category="FW/ufw"

    # ufwが有効か
    local ufw_status
    ufw_status=$(ufw status 2>/dev/null)

    if echo "$ufw_status" | grep -q "Status: active"; then
        record "OK" "$category" "ufw active"
    else
        record "FAIL" "$category" "ufwが無効です"
        return
    fi

    # 許可ポートの確認（80, 443は ANY から許可）
    for port in 80 443; do
        if echo "$ufw_status" | grep -q "${port}/tcp.*ALLOW"; then
            record "OK" "$category" "ポート${port} ALLOW"
        else
            record "WARN" "$category" "ポート${port} のALLOWルールが見つかりません"
        fi
    done

    # SSHが特定IPに制限されているか（Anywhere from になっていないか）
    local ssh_lines
    ssh_lines=$(echo "$ufw_status" | grep "22/tcp" | grep "ALLOW")
    if [[ -z "$ssh_lines" ]]; then
        record "WARN" "$category" "SSH(22)のALLOWルールがありません"
    elif echo "$ssh_lines" | grep -q "Anywhere"; then
        record "WARN" "$category" "SSH(22)が全IPに開放されています（管理者IPに制限推奨）"
    else
        record "OK" "$category" "SSH(22) IP制限あり"
    fi

    # 想定外のポートが開いていないか
    local unexpected
    unexpected=$(echo "$ufw_status" | grep "ALLOW" | grep -v -E "(22|80|443)" | grep -v "(v6)" || true)
    if [[ -n "$unexpected" ]]; then
        record "WARN" "$category" "想定外の許可ルールあり: $(echo "$unexpected" | head -3)"
    fi

    # デフォルトポリシーがdenyであること
    local verbose_status
    verbose_status=$(ufw status verbose 2>/dev/null)
    if echo "$verbose_status" | grep -q "Default:.*deny (incoming)"; then
        record "OK" "$category" "デフォルトポリシー: deny (incoming)"
    else
        record "FAIL" "$category" "デフォルトポリシーがdeny (incoming)ではありません"
    fi

    # ポート5432が外部公開されていないこと
    if echo "$ufw_status" | grep -q "5432.*ALLOW"; then
        record "FAIL" "$category" "ポート5432(PostgreSQL)が外部に公開されています"
    else
        record "OK" "$category" "ポート5432 外部非公開"
    fi
}

# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------
check_pg_listen_addresses() {
    local category="PostgreSQL/listen_addresses"

    # Docker運用: コンテナ内の listen_addresses='*' は正常
    # ホスト側のportsバインドが 127.0.0.1 に制限されているかを確認
    local container_name="${DBMS_CONTAINER:-dbms_pgsql}"

    if ! docker inspect "$container_name" &>/dev/null; then
        record "WARN" "$category" "コンテナ ${container_name} が見つかりません"
        return
    fi

    # ホスト側ポートバインドを確認（0.0.0.0 = 全IF公開）
    local host_binding
    host_binding=$(docker inspect --format='{{range $p, $conf := .NetworkSettings.Ports}}{{range $conf}}{{.HostIp}}:{{.HostPort}}{{end}}{{end}}' "$container_name" 2>/dev/null)

    if echo "$host_binding" | grep -q "0.0.0.0"; then
        record "WARN" "$category" "PostgreSQLコンテナが全IF公開: ${host_binding}（127.0.0.1バインド推奨）"
    elif echo "$host_binding" | grep -q "127.0.0.1"; then
        record "OK" "$category" "PostgreSQLコンテナは localhost のみ: ${host_binding}"
    else
        # portsマッピングなし or 空 = 外部公開なし
        record "OK" "$category" "PostgreSQLコンテナにホスト側ポート公開なし"
    fi
}

check_pg_hba() {
    local category="PostgreSQL/pg_hba認証方式"
    local hba_file
    hba_file=$(find "$DBMS_CONF_DIR" -name "$DBMS_HBA_FILE" 2>/dev/null | head -1)

    if [[ -z "$hba_file" ]]; then
        record "WARN" "$category" "${DBMS_HBA_FILE}が見つかりません"
        return
    fi

    # DB/ユーザー個別エントリ or "all" ワイルドカードエントリを検索
    local hba_line
    hba_line=$(grep -E "(${DB_NAME}|all)\s.*(${DB_USER}|all)" "$hba_file" 2>/dev/null \
        | grep -v "^#" | grep -v "replication" || true)

    if [[ -z "$hba_line" ]]; then
        record "WARN" "$category" "${DB_NAME}/${DB_USER}に該当するエントリが見つかりません"
    elif echo "$hba_line" | grep -q "scram-sha-256"; then
        record "OK" "$category" "${DB_NAME}/${DB_USER} scram-sha-256（該当行: $(echo "$hba_line" | head -1 | xargs)）"
    elif echo "$hba_line" | grep -q "trust"; then
        record "WARN" "$category" "${DB_NAME}/${DB_USER} がtrust認証です（scram-sha-256推奨）"
    else
        record "FAIL" "$category" "${DB_NAME}/${DB_USER}の認証方式がscram-sha-256ではありません"
    fi
}

# ---------------------------------------------------------------------------
# fail2ban
# ---------------------------------------------------------------------------
check_fail2ban() {
    local category="fail2ban/lisanima-pin"

    if ! command -v fail2ban-client &>/dev/null; then
        record "FAIL" "$category" "fail2banがインストールされていません"
        return
    fi

    local jail_status
    jail_status=$(fail2ban-client status lisanima-pin 2>/dev/null)

    if [[ $? -ne 0 ]] || [[ -z "$jail_status" ]]; then
        record "FAIL" "$category" "lisanima-pin jailが無効またはエラー"
        return
    fi

    record "OK" "$category" "lisanima-pin jail active"

    # maxretry = 5 であること
    local maxretry
    maxretry=$(fail2ban-client get lisanima-pin maxretry 2>/dev/null)
    if [[ "$maxretry" == "${FAIL2BAN_MAXRETRY}" ]]; then
        record "OK" "$category" "maxretry = ${FAIL2BAN_MAXRETRY}"
    else
        record "WARN" "$category" "maxretry = ${maxretry:-不明}（${FAIL2BAN_MAXRETRY}であるべき）"
    fi

    # bantime = 86400 であること
    local bantime
    bantime=$(fail2ban-client get lisanima-pin bantime 2>/dev/null)
    if [[ "$bantime" == "${FAIL2BAN_BANTIME}" ]]; then
        record "OK" "$category" "bantime = ${FAIL2BAN_BANTIME}（24時間）"
    else
        record "WARN" "$category" "bantime = ${bantime:-不明}（${FAIL2BAN_BANTIME}であるべき）"
    fi

    # 直近24時間のバン件数（fail2ban-clientから現在のバン数を取得）
    local banned_count
    banned_count=$(echo "$jail_status" | grep "Currently banned" | awk '{print $NF}')
    local total_banned
    total_banned=$(echo "$jail_status" | grep "Total banned" | awk '{print $NF}')

    if [[ -n "$total_banned" ]] && [[ "$total_banned" -gt 0 ]]; then
        record "WARN" "$category" "バン実績あり（現在: ${banned_count:-0}, 累計: ${total_banned}）"
    else
        record "OK" "$category" "バン件数: 0"
    fi
}

# ---------------------------------------------------------------------------
# サービス稼働
# ---------------------------------------------------------------------------
check_service() {
    local category="サービス/lisanima"

    if systemctl is-active --quiet lisanima.service 2>/dev/null; then
        record "OK" "$category" "lisanima.service active(running)"
    else
        record "FAIL" "$category" "lisanima.serviceが停止しています"
    fi
}

check_port_8765() {
    local category="サービス/ポート${LISANIMA_PORT}"

    if ss -tlnp 2>/dev/null | grep -q "127.0.0.1:${LISANIMA_PORT}"; then
        record "OK" "$category" "127.0.0.1:${LISANIMA_PORT} リッスン中"
    else
        record "FAIL" "$category" "127.0.0.1:${LISANIMA_PORT} がリッスンされていません"
    fi
}

check_nginx_service() {
    local category="サービス/nginx"

    if systemctl is-active --quiet nginx 2>/dev/null; then
        record "OK" "$category" "nginx active"
    else
        record "FAIL" "$category" "nginxが停止しています"
    fi
}

check_postgresql_service() {
    local category="サービス/postgresql"
    local container_name="${DBMS_CONTAINER:-dbms_pgsql}"

    local status
    status=$(docker inspect --format='{{.State.Status}}' "$container_name" 2>/dev/null)

    if [[ "$status" == "running" ]]; then
        record "OK" "$category" "コンテナ ${container_name} running"
    else
        record "FAIL" "$category" "コンテナ ${container_name} が停止しています（status: ${status:-不明}）"
    fi
}

# ---------------------------------------------------------------------------
# ファイル権限
# ---------------------------------------------------------------------------
check_env_permissions() {
    local category="ファイル権限/.env"

    if [[ ! -f "$ENV_FILE" ]]; then
        record "FAIL" "$category" ".envファイルが存在しません: ${ENV_FILE}"
        return
    fi

    local perms
    perms=$(stat -c '%a' "$ENV_FILE" 2>/dev/null)

    if [[ "$perms" == "600" ]]; then
        record "OK" "$category" ".env パーミッション 600"
    else
        record "FAIL" "$category" ".env パーミッションが ${perms}（600であるべき）"
    fi

    # 所有者がnatosepiaであること
    local owner
    owner=$(stat -c '%U' "$ENV_FILE" 2>/dev/null)
    if [[ "$owner" == "natosepia" ]]; then
        record "OK" "$category" ".env 所有者: natosepia"
    else
        record "FAIL" "$category" ".env 所有者が ${owner}（natosepiaであるべき）"
    fi
}

check_env_gitignore() {
    local category="ファイル権限/.gitignore"
    local gitignore="${PROJECT_DIR}/.gitignore"

    if [[ ! -f "$gitignore" ]]; then
        record "WARN" "$category" ".gitignoreファイルが存在しません"
        return
    fi

    if grep -qE "^\.env$|^\.env\s" "$gitignore" 2>/dev/null; then
        record "OK" "$category" ".env は .gitignore に含まれている"
    else
        record "FAIL" "$category" ".env が .gitignore に含まれていません"
    fi
}

# ---------------------------------------------------------------------------
# OAuthクリーンアップ（DB）
# ---------------------------------------------------------------------------
check_oauth_cleanup() {
    local category="OAuth/期限切れトークン"
    local container_name="${DBMS_CONTAINER:-dbms_pgsql}"

    # コンテナが稼働しているか
    if ! docker inspect "$container_name" &>/dev/null; then
        record "WARN" "$category" "コンテナ ${container_name} が見つかりません"
        return
    fi

    # 期限切れアクセストークン数
    local expired_tokens
    expired_tokens=$(docker exec "$container_name" psql -U "${DB_USER}" -d "${DB_NAME}" -tAc \
        "SELECT COUNT(*) FROM t_oauth_access_token WHERE expires_at < NOW();" 2>/dev/null)

    if [[ -n "$expired_tokens" ]] && [[ "$expired_tokens" -gt 0 ]]; then
        record "WARN" "$category" "期限切れトークン: ${expired_tokens}件（定期削除を推奨）"
    elif [[ -n "$expired_tokens" ]]; then
        record "OK" "$category" "期限切れトークン: 0件"
    else
        record "WARN" "$category" "トークンテーブルの参照に失敗"
    fi

    # 期限切れクライアント数（全トークンが失効済み）
    local category2="OAuth/期限切れクライアント"
    local stale_clients
    stale_clients=$(docker exec "$container_name" psql -U "${DB_USER}" -d "${DB_NAME}" -tAc \
        "SELECT COUNT(*) FROM m_oauth_client c
         WHERE NOT EXISTS (
             SELECT 1 FROM t_oauth_access_token t
             WHERE t.client_id = c.client_id
               AND t.expires_at >= NOW()
         )
         AND EXISTS (
             SELECT 1 FROM t_oauth_access_token t
             WHERE t.client_id = c.client_id
         );" 2>/dev/null)

    if [[ -n "$stale_clients" ]] && [[ "$stale_clients" -gt 0 ]]; then
        record "WARN" "$category2" "全トークン失効済みクライアント: ${stale_clients}件（削除候補）"
    elif [[ -n "$stale_clients" ]]; then
        record "OK" "$category2" "失効済みクライアント: 0件"
    else
        record "WARN" "$category2" "クライアントテーブルの参照に失敗"
    fi
}

# =============================================================================
# メイン処理
# =============================================================================
main() {
    # root権限チェック
    if [[ "$(id -u)" -ne 0 ]]; then
        echo "ERROR: このスクリプトはroot権限で実行してください（sudo bash $0）" >&2
        exit 1
    fi

    local start_time
    start_time=$(date '+%Y-%m-%d %H:%M:%S')

    # 全チェック実行
    check_tls_cert_expiry
    check_tls_protocol
    #check_ocsp_stapling
    check_tls_session_tickets
    #check_certbot_timer
    check_security_headers
    check_csp_pin_page
    check_xss_protection
    check_nginx_rate_limit
    #check_firewall
    check_pg_listen_addresses
    check_pg_hba
    check_fail2ban
    check_nginx_service
    check_postgresql_service
    check_service
    check_port_8765
    check_env_permissions
    check_env_gitignore
    check_oauth_cleanup

    # サマリ作成
    local total=$((COUNT_OK + COUNT_WARN + COUNT_FAIL))
    local summary="=== 監査サマリ (${start_time}) === OK: ${COUNT_OK} / WARN: ${COUNT_WARN} / FAIL: ${COUNT_FAIL} / Total: ${total}"

    # 出力生成
    local output=""
    output+="========================================\n"
    output+=" lisanima インフラセキュリティ監査\n"
    output+=" 実行日時: ${start_time}\n"
    output+="========================================\n\n"

    for line in "${RESULTS[@]}"; do
        output+="${line}\n"
    done

    output+="\n${summary}\n"
    output+="========================================\n"

    # ログファイルには常に全結果を書き込む
    echo -e "$output" >> "${LOG_FILE}"

    # --quiet モード: WARN/FAILがなければサマリのみstdout
    if [[ "$QUIET" == true ]]; then
        if [[ $COUNT_WARN -eq 0 ]] && [[ $COUNT_FAIL -eq 0 ]]; then
            echo "$summary"
            return 0
        fi
        # WARN/FAILがある場合はWARN/FAIL行+サマリのみstdout
        for line in "${RESULTS[@]}"; do
            if echo "$line" | grep -qE "(WARN|FAIL):"; then
                echo "$line"
            fi
        done
        echo "$summary"
    else
        # 通常モード: 全結果をstdout
        echo -e "$output"
    fi

    # FAIL があれば終了コード1（cron通知連携用）
    if [[ $COUNT_FAIL -gt 0 ]]; then
        return 1
    fi
    return 0
}

main
