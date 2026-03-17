"""lisanima MCPサーバー エントリポイント

FastMCP を使用し、リサの記憶管理ツールを提供する。
stdioモード（Claude Code用）とStreamable HTTPモード（リモート接続用）を切替可能。
HTTPモードではOAuth 2.1認証を有効にする。
"""
import argparse
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import Response

from lisanima.db import db_pool
from lisanima.interface.remember import remember as remember_impl
from lisanima.interface.recall import recall as recall_impl

# stdoutはMCPプロトコル通信に使うため、loggingはstderrに出す
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def _parseArgs() -> argparse.Namespace:
    """コマンドライン引数をパースする。

    Returns:
        パース済みの引数Namespace
    """
    parser = argparse.ArgumentParser(description="lisanima MCPサーバー")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Streamable HTTPモードで起動する（デフォルトはstdio）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="HTTPモード時のリッスンポート（デフォルト: 8765）",
    )
    return parser.parse_args()


# 起動モード判定（モジュール読み込み時にFastMCPインスタンスを構築するため先に判定）
_args = _parseArgs()


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[None]:
    """サーバーのライフサイクル管理。

    起動時にDB接続プールを開き、終了時に閉じる。
    """
    await db_pool.open()
    logger.info("lisanima MCPサーバー起動")
    try:
        yield
    finally:
        await db_pool.close()
        logger.info("lisanima MCPサーバー終了")


def _createMcp() -> FastMCP:
    """FastMCPインスタンスを生成する。

    HTTPモード時はOAuth 2.1認証を有効にする。
    stdioモード時は認証なし（ローカル通信のため不要）。
    """
    if _args.http:
        from mcp.server.auth.settings import (
            AuthSettings,
            ClientRegistrationOptions,
            RevocationOptions,
        )
        from lisanima.auth.provider import LisanimaOAuthProvider

        fqdn = os.environ.get("LISANIMA_FQDN")
        if not fqdn:
            raise RuntimeError(
                "環境変数 LISANIMA_FQDN が未設定です。"
                "HTTPモードでは LISANIMA_FQDN の設定が必須です。"
            )

        auth_settings = AuthSettings(
            issuer_url=f"https://{fqdn}",
            resource_server_url=f"https://{fqdn}/lisanima/mcp",
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=[],
            ),
            revocation_options=RevocationOptions(enabled=True),
        )
        oauth_provider = LisanimaOAuthProvider()

        server = FastMCP(
            "lisanima",
            lifespan=lifespan,
            auth=auth_settings,
            auth_server_provider=oauth_provider,
        )
        logger.info("OAuth 2.1 認証有効")
    else:
        server = FastMCP("lisanima", lifespan=lifespan)

    return server


mcp = _createMcp()


# ----------------------------------------------------------
# /auth/pin カスタムルート（OAuth認証なしで公開）
# ----------------------------------------------------------
if _args.http:
    from lisanima.auth.pin import handlePinGet, handlePinPost

    @mcp.custom_route("/auth/pin", methods=["GET", "POST"])
    async def pin_handler(request: Request) -> Response:
        """PIN認証画面（GET: フォーム表示, POST: PIN検証）。"""
        if request.method == "GET":
            return await handlePinGet(request)
        return await handlePinPost(request)


# ----------------------------------------------------------
# MCPツール登録
# ----------------------------------------------------------

@mcp.tool()
async def remember(
    content: str,
    speaker: str,
    target: str | None = None,
    emotion: dict | None = None,
    tags: list[str] | None = None,
    project: str | None = None,
    session_date: str | None = None,
) -> dict:
    """記憶を保存する。

    セッション中の発言・知見をDBに永続化する。
    セッションは日付単位で自動管理される。

    Args:
        content: 発言・記憶の内容
        speaker: 発言者名（リサ / なとせ / ありす / 桃華 / ほたる / 晶葉）
        target: 発言先（省略時はbroadcast）
        emotion: 感情値 {"joy": 0-255, "anger": 0-255, "sorrow": 0-255, "fun": 0-255}
        tags: タグ名の配列（連想記憶用）
        project: プロジェクト名
        session_date: セッション日付 YYYY-MM-DD（省略時は今日）
    """
    return await remember_impl(
        content=content,
        speaker=speaker,
        target=target,
        emotion=emotion,
        tags=tags,
        project=project,
        session_date=session_date,
    )


@mcp.tool()
async def recall(
    query: str | None = None,
    tags: list[str] | None = None,
    speaker: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_emotion: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """記憶を検索する。

    過去の記憶をキーワード・タグ・日付・感情値で検索する。
    全パラメータ省略時は最新20件を返却。

    Args:
        query: 全文検索キーワード
        tags: タグ名でフィルタ（AND検索）
        speaker: 発言者でフィルタ
        date_from: 日付範囲の開始（YYYY-MM-DD）
        date_to: 日付範囲の終了（YYYY-MM-DD）
        min_emotion: 感情値合計の下限
        limit: 取得件数上限（デフォルト: 20）
        offset: オフセット（デフォルト: 0）
    """
    return await recall_impl(
        query=query,
        tags=tags,
        speaker=speaker,
        date_from=date_from,
        date_to=date_to,
        min_emotion=min_emotion,
        limit=limit,
        offset=offset,
    )


def main():
    """MCPサーバーを起動する。

    引数なし: stdioモード（Claude Code用）
    --http: Streamable HTTPモード（リモートDesktop App用）
    --port: HTTPモード時のポート指定（デフォルト: 8765）
    """
    if _args.http:
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = _args.port
        logger.info("Streamable HTTPモードで起動 (port=%d)", _args.port)
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
