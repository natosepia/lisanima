"""OAuthAuthorizationServerProvider 実装

FastMCP の OAuthAuthorizationServerProvider Protocol に準拠し、
PostgreSQL をストレージとする OAuth 2.1 認可サーバーを提供する。
"""
import logging
import secrets
from dataclasses import dataclass

from mcp.server.auth.provider import (
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from lisanima.db import db_pool
from lisanima.repositories import oauth_repo

logger = logging.getLogger(__name__)


@dataclass
class AuthorizationCode:
    """認可コードのドメインオブジェクト。

    FastMCPのTokenHandlerが expires_at, client_id, redirect_uri,
    redirect_uri_provided_explicitly, code_challenge, scopes を参照する。
    expires_at は Unix timestamp（float）。
    """
    code: str
    client_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    code_challenge: str
    code_challenge_method: str
    scopes: list[str]
    expires_at: float
    resource: str | None


@dataclass
class RefreshToken:
    """リフレッシュトークンのドメインオブジェクト。

    FastMCPのTokenHandlerが expires_at, client_id, scopes を参照する。
    """
    token: str
    client_id: str
    scopes: list[str]
    expires_at: float


@dataclass
class AccessToken:
    """アクセストークンのドメインオブジェクト。

    FastMCPのBearerAuthBackendが expires_at, client_id, scopes を参照する。
    """
    token: str
    client_id: str
    scopes: list[str]
    expires_at: float
    resource: str | None


class LisanimaOAuthProvider:
    """lisanima OAuth 2.1 Provider

    FastMCP の OAuthAuthorizationServerProvider Protocol を実装する。
    トークン・クライアント情報は全て PostgreSQL に永続化。
    """

    # ----------------------------------------------------------
    # クライアント管理
    # ----------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """クライアント情報を取得する。"""
        async with db_pool.get_connection() as conn:
            json_str = await oauth_repo.loadClient(conn, client_id)
        if json_str is None:
            return None
        return OAuthClientInformationFull.model_validate_json(json_str)

    async def register_client(
        self, client_info: OAuthClientInformationFull
    ) -> None:
        """クライアントを動的登録する（RFC 7591）。

        client_id / client_secret を生成し、client_info に設定してからDBに保存する。
        """
        client_info.client_id = secrets.token_urlsafe(16)
        client_info.client_secret = secrets.token_urlsafe(32)
        client_info.client_id_issued_at = int(
            oauth_repo._utcnow().timestamp()
        )

        async with db_pool.get_connection() as conn:
            async with conn.transaction():
                await oauth_repo.saveClient(
                    conn,
                    client_info.client_id,
                    client_info.model_dump_json(),
                )
        logger.info("OAuthクライアント登録: %s", client_info.client_id)

    # ----------------------------------------------------------
    # 認可
    # ----------------------------------------------------------

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        """認可URLを返す。PIN入力画面にリダイレクトさせる。

        AuthorizationParamsを一時保存し、/auth/pin のURLを返す。
        FastMCPがこのURLに302リダイレクトする。
        """
        async with db_pool.get_connection() as conn:
            async with conn.transaction():
                session_id = await oauth_repo.saveAuthSession(
                    conn,
                    client_id=client.client_id,
                    redirect_uri=str(params.redirect_uri),
                    state=params.state,
                    scopes=params.scopes or [],
                    code_challenge=params.code_challenge,
                    # OAuth 2.1仕様でS256必須。FastMCPのauthorize handlerがバリデーション済み
                    code_challenge_method="S256",
                    redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                    resource=getattr(params, "resource", None),
                )
        logger.info("認可セッション作成: session_id=%s", session_id)
        return f"/auth/pin?session_id={session_id}"

    # ----------------------------------------------------------
    # 認可コード
    # ----------------------------------------------------------

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        """認可コードを読み込む。"""
        async with db_pool.get_connection() as conn:
            row = await oauth_repo.loadAuthCode(conn, authorization_code)
        if row is None:
            return None
        if row["client_id"] != client.client_id:
            return None
        return AuthorizationCode(
            code=row["code"],
            client_id=row["client_id"],
            redirect_uri=row["redirect_uri"],
            redirect_uri_provided_explicitly=row["redirect_uri_provided_explicitly"],
            code_challenge=row["code_challenge"],
            code_challenge_method=row["code_challenge_method"],
            scopes=row["scopes"],
            expires_at=row["expires_at"].timestamp(),
            resource=row.get("resource"),
        )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        """認可コードをアクセストークン+リフレッシュトークンに交換する。

        認可コードは1回使い切りのため、交換後に削除する。
        """
        async with db_pool.get_connection() as conn:
            async with conn.transaction():
                # 認可コード削除（1回使い切り）
                await oauth_repo.deleteAuthCode(conn, authorization_code.code)

                # アクセストークン発行
                access_token, expires_in = await oauth_repo.saveAccessToken(
                    conn,
                    client_id=client.client_id,
                    scopes=authorization_code.scopes,
                    resource=authorization_code.resource,
                )

                # リフレッシュトークン発行
                refresh_token = await oauth_repo.saveRefreshToken(
                    conn,
                    client_id=client.client_id,
                    scopes=authorization_code.scopes,
                )

        logger.info("認可コード交換完了: client_id=%s", client.client_id)
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=expires_in,
            refresh_token=refresh_token,
            scope=" ".join(authorization_code.scopes) if authorization_code.scopes else None,
        )

    # ----------------------------------------------------------
    # リフレッシュトークン
    # ----------------------------------------------------------

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        """リフレッシュトークンを読み込む。"""
        async with db_pool.get_connection() as conn:
            row = await oauth_repo.loadRefreshToken(conn, refresh_token)
        if row is None:
            return None
        if row["client_id"] != client.client_id:
            return None
        return RefreshToken(
            token=row["token"],
            client_id=row["client_id"],
            scopes=row["scopes"],
            expires_at=row["expires_at"].timestamp(),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """リフレッシュトークンで新しいアクセストークンを発行する。

        旧リフレッシュトークンを削除し、新しいペアを発行する（トークンローテーション）。
        """
        effective_scopes = scopes if scopes else refresh_token.scopes

        async with db_pool.get_connection() as conn:
            async with conn.transaction():
                # 旧リフレッシュトークン削除
                await oauth_repo.deleteRefreshToken(conn, refresh_token.token)

                # 新しいアクセストークン発行
                access_token, expires_in = await oauth_repo.saveAccessToken(
                    conn,
                    client_id=client.client_id,
                    scopes=effective_scopes,
                    resource=None,
                )

                # 新しいリフレッシュトークン発行
                new_refresh = await oauth_repo.saveRefreshToken(
                    conn,
                    client_id=client.client_id,
                    scopes=effective_scopes,
                )

        logger.info("トークンリフレッシュ完了: client_id=%s", client.client_id)
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=expires_in,
            refresh_token=new_refresh,
            scope=" ".join(effective_scopes) if effective_scopes else None,
        )

    # ----------------------------------------------------------
    # アクセストークン検証
    # ----------------------------------------------------------

    async def load_access_token(self, token: str) -> AccessToken | None:
        """アクセストークンを読み込む。"""
        async with db_pool.get_connection() as conn:
            row = await oauth_repo.loadAccessToken(conn, token)
        if row is None:
            return None
        return AccessToken(
            token=row["token"],
            client_id=row["client_id"],
            scopes=row["scopes"],
            expires_at=row["expires_at"].timestamp(),
            resource=row.get("resource"),
        )

    # ----------------------------------------------------------
    # トークン無効化
    # ----------------------------------------------------------

    async def revoke_token(
        self,
        token: AccessToken | RefreshToken,
    ) -> None:
        """トークンを無効化する。

        RFC 7009推奨: アクセストークンと対応するリフレッシュトークンの両方を無効化。
        client_id単位で対応するペアを全削除する。
        """
        async with db_pool.get_connection() as conn:
            async with conn.transaction():
                if isinstance(token, AccessToken):
                    await oauth_repo.deleteAccessToken(conn, token.token)
                    # 同一クライアントのリフレッシュトークンも無効化
                    await oauth_repo.deleteRefreshTokensByClientId(
                        conn, token.client_id
                    )
                    logger.info("トークン無効化（AT+RT）: client_id=%s", token.client_id)
                elif isinstance(token, RefreshToken):
                    await oauth_repo.deleteRefreshToken(conn, token.token)
                    # 同一クライアントのアクセストークンも無効化
                    await oauth_repo.deleteAccessTokensByClientId(
                        conn, token.client_id
                    )
                    logger.info("トークン無効化（RT+AT）: client_id=%s", token.client_id)
