"""OAuthリポジトリ

OAuth 2.1 関連テーブルへのCRUD操作を提供する。
m_oauth_client, t_oauth_auth_session, t_oauth_auth_code,
t_oauth_access_token, t_oauth_refresh_token を管理。
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone

from psycopg import AsyncConnection, sql

logger = logging.getLogger(__name__)

# トークン有効期限（秒）
ACCESS_TOKEN_EXPIRES = 3600       # 1時間
REFRESH_TOKEN_EXPIRES = 2592000   # 30日
AUTH_CODE_EXPIRES = 300           # 5分
AUTH_SESSION_EXPIRES = 600        # 10分


def _generateToken(nbytes: int = 32) -> str:
    """暗号学的に安全なランダムトークンを生成する。"""
    return secrets.token_urlsafe(nbytes)


def _utcnow() -> datetime:
    """UTC現在時刻を返す。"""
    return datetime.now(timezone.utc)


# ============================================================
# m_oauth_client
# ============================================================

async def saveClient(
    conn: AsyncConnection,
    client_id: str,
    client_info_json: str,
) -> None:
    """OAuthクライアント情報を保存する。

    Args:
        conn: DB接続
        client_id: クライアントID
        client_info_json: OAuthClientInformationFullのJSON文字列
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO m_oauth_client (client_id, client_info)
            VALUES (%s, %s::jsonb)
            ON CONFLICT (client_id) DO UPDATE SET client_info = EXCLUDED.client_info
            """,
            (client_id, client_info_json),
        )
    logger.debug("OAuthクライアント保存: %s", client_id)


async def loadClient(
    conn: AsyncConnection,
    client_id: str,
) -> str | None:
    """OAuthクライアント情報のJSON文字列を取得する。

    Args:
        conn: DB接続
        client_id: クライアントID

    Returns:
        client_info JSON文字列。未登録ならNone
    """
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT client_info::text FROM m_oauth_client WHERE client_id = %s",
            (client_id,),
        )
        row = await cur.fetchone()
    return row["client_info"] if row else None


# ============================================================
# t_oauth_auth_session
# ============================================================

async def saveAuthSession(
    conn: AsyncConnection,
    client_id: str,
    redirect_uri: str,
    state: str | None,
    scopes: list[str],
    code_challenge: str,
    code_challenge_method: str,
    redirect_uri_provided_explicitly: bool,
    resource: str | None,
) -> str:
    """認可セッションを保存する。

    Args:
        conn: DB接続
        (以下、AuthorizationParamsから受け渡し)

    Returns:
        生成されたsession_id
    """
    session_id = _generateToken()
    expires_at = _utcnow() + timedelta(seconds=AUTH_SESSION_EXPIRES)

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO t_oauth_auth_session
                (session_id, client_id, redirect_uri, state, scopes,
                 code_challenge, code_challenge_method,
                 redirect_uri_provided_explicitly, resource, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                session_id, client_id, redirect_uri, state, scopes,
                code_challenge, code_challenge_method,
                redirect_uri_provided_explicitly, resource, expires_at,
            ),
        )
    logger.debug("認可セッション保存: %s", session_id)
    return session_id


async def loadAuthSession(
    conn: AsyncConnection,
    session_id: str,
) -> dict | None:
    """認可セッションを取得する（有効期限チェック込み）。

    Args:
        conn: DB接続
        session_id: セッションID

    Returns:
        セッション情報dict。期限切れまたは未存在ならNone
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT * FROM t_oauth_auth_session
            WHERE session_id = %s AND expires_at > NOW()
            """,
            (session_id,),
        )
        return await cur.fetchone()


async def deleteAuthSession(
    conn: AsyncConnection,
    session_id: str,
) -> None:
    """認可セッションを削除する。"""
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM t_oauth_auth_session WHERE session_id = %s",
            (session_id,),
        )


# ============================================================
# t_oauth_auth_code
# ============================================================

async def saveAuthCode(
    conn: AsyncConnection,
    client_id: str,
    redirect_uri: str,
    redirect_uri_provided_explicitly: bool,
    code_challenge: str,
    code_challenge_method: str,
    scopes: list[str],
    resource: str | None,
) -> str:
    """認可コードを生成・保存する。

    Returns:
        生成された認可コード
    """
    code = _generateToken()
    expires_at = _utcnow() + timedelta(seconds=AUTH_CODE_EXPIRES)

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO t_oauth_auth_code
                (code, client_id, redirect_uri, redirect_uri_provided_explicitly,
                 code_challenge, code_challenge_method, scopes, resource, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                code, client_id, redirect_uri, redirect_uri_provided_explicitly,
                code_challenge, code_challenge_method, scopes, resource, expires_at,
            ),
        )
    logger.debug("認可コード保存: %s...", code[:8])
    return code


async def loadAuthCode(
    conn: AsyncConnection,
    code: str,
) -> dict | None:
    """認可コードを取得する（有効期限チェック込み）。

    Returns:
        認可コード情報dict。期限切れまたは未存在ならNone
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT * FROM t_oauth_auth_code
            WHERE code = %s AND expires_at > NOW()
            """,
            (code,),
        )
        return await cur.fetchone()


async def deleteAuthCode(
    conn: AsyncConnection,
    code: str,
) -> None:
    """認可コードを削除する（1回使い切り）。"""
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM t_oauth_auth_code WHERE code = %s",
            (code,),
        )


# ============================================================
# t_oauth_access_token
# ============================================================

async def saveAccessToken(
    conn: AsyncConnection,
    client_id: str,
    scopes: list[str],
    resource: str | None,
) -> tuple[str, int]:
    """アクセストークンを生成・保存する。

    Returns:
        (トークン文字列, expires_in秒数) のタプル
    """
    token = _generateToken()
    expires_at = _utcnow() + timedelta(seconds=ACCESS_TOKEN_EXPIRES)

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO t_oauth_access_token
                (token, client_id, scopes, resource, expires_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (token, client_id, scopes, resource, expires_at),
        )
    logger.debug("アクセストークン発行: %s...", token[:8])
    return token, ACCESS_TOKEN_EXPIRES


async def loadAccessToken(
    conn: AsyncConnection,
    token: str,
) -> dict | None:
    """アクセストークンを取得する（有効期限チェック込み）。

    Returns:
        トークン情報dict。期限切れまたは未存在ならNone
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT * FROM t_oauth_access_token
            WHERE token = %s AND expires_at > NOW()
            """,
            (token,),
        )
        return await cur.fetchone()


async def deleteAccessToken(
    conn: AsyncConnection,
    token: str,
) -> None:
    """アクセストークンを削除する。"""
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM t_oauth_access_token WHERE token = %s",
            (token,),
        )


# ============================================================
# t_oauth_refresh_token
# ============================================================

async def saveRefreshToken(
    conn: AsyncConnection,
    client_id: str,
    scopes: list[str],
) -> str:
    """リフレッシュトークンを生成・保存する。

    Returns:
        トークン文字列
    """
    token = _generateToken()
    expires_at = _utcnow() + timedelta(seconds=REFRESH_TOKEN_EXPIRES)

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO t_oauth_refresh_token
                (token, client_id, scopes, expires_at)
            VALUES (%s, %s, %s, %s)
            """,
            (token, client_id, scopes, expires_at),
        )
    logger.debug("リフレッシュトークン発行: %s...", token[:8])
    return token


async def loadRefreshToken(
    conn: AsyncConnection,
    token: str,
) -> dict | None:
    """リフレッシュトークンを取得する（有効期限チェック込み）。

    Returns:
        トークン情報dict。期限切れまたは未存在ならNone
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT * FROM t_oauth_refresh_token
            WHERE token = %s AND expires_at > NOW()
            """,
            (token,),
        )
        return await cur.fetchone()


async def deleteRefreshToken(
    conn: AsyncConnection,
    token: str,
) -> None:
    """リフレッシュトークンを削除する。"""
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM t_oauth_refresh_token WHERE token = %s",
            (token,),
        )


async def deleteAccessTokensByClientId(
    conn: AsyncConnection,
    client_id: str,
) -> None:
    """指定クライアントの全アクセストークンを削除する。"""
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM t_oauth_access_token WHERE client_id = %s",
            (client_id,),
        )


async def deleteRefreshTokensByClientId(
    conn: AsyncConnection,
    client_id: str,
) -> None:
    """指定クライアントの全リフレッシュトークンを削除する。"""
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM t_oauth_refresh_token WHERE client_id = %s",
            (client_id,),
        )


# ============================================================
# 期限切れトークン掃除
# ============================================================

async def cleanupExpiredTokens(conn: AsyncConnection) -> dict[str, int]:
    """期限切れのトークン・セッションを一括削除する。

    Returns:
        {"auth_sessions": n, "auth_codes": n, "access_tokens": n, "refresh_tokens": n}
    """
    counts = {}
    tables = [
        ("auth_sessions", "t_oauth_auth_session"),
        ("auth_codes", "t_oauth_auth_code"),
        ("access_tokens", "t_oauth_access_token"),
        ("refresh_tokens", "t_oauth_refresh_token"),
    ]
    async with conn.cursor() as cur:
        for key, table in tables:
            await cur.execute(
                sql.SQL("DELETE FROM {} WHERE expires_at < NOW()").format(
                    sql.Identifier(table)
                )
            )
            counts[key] = cur.rowcount

    logger.info("期限切れトークン掃除: %s", counts)
    return counts
