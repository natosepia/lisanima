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
from lisanima.interface.forget import forget as forget_impl
from lisanima.interface.organize import organize as organize_impl
from lisanima.interface.recall import recall as recall_impl
from lisanima.interface.remember import remember as remember_impl
from lisanima.interface.rulebook import rulebook as rulebook_impl
from lisanima.interface.topics import topicManage as topic_manage_impl

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
    topic_id: int | None = None,
    project: str | None = None,
    session_date: str | None = None,
) -> dict:
    """記憶を保存する。

    セッション中の発言・知見をDBに永続化する。
    セッションは日付単位で自動管理される。
    タグ付けは organize コマンドで行う。

    Args:
        content: 発言・記憶の内容
        speaker: 発言者名（リサ / なとせ / ありす / 桃華 / ほたる / 晶葉）
        target: 発言先（省略時はbroadcast）
        emotion: 感情値 {"joy": 0-255, "anger": 0-255, "sorrow": 0-255, "fun": 0-255}
        topic_id: トピックID（指定時はセッションとトピックの紐付けも自動作成）
        project: プロジェクト名
        session_date: セッション日付 YYYY-MM-DD（省略時は今日）
    """
    return await remember_impl(
        content=content,
        speaker=speaker,
        target=target,
        emotion=emotion,
        topic_id=topic_id,
        project=project,
        session_date=session_date,
    )


@mcp.tool()
async def recall(
    query: list[str] | None = None,
    tags: list[str] | None = None,
    speaker: str | None = None,
    project: str | None = None,
    topic_id: list[int] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    emotion_filter: dict | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """記憶を検索する。

    過去の記憶をキーワード・タグ・日付・感情値で検索する。
    全パラメータ省略時は最新20件を返却。

    Args:
        query: 全文検索キーワード（AND検索）
        tags: タグ名でフィルタ（AND検索）
        speaker: 発言者でフィルタ
        project: プロジェクト名でフィルタ
        topic_id: トピックIDでフィルタ（OR検索）
        date_from: 日付範囲の開始（YYYY-MM-DD）
        date_to: 日付範囲の終了（YYYY-MM-DD）
        emotion_filter: 感情値のレンジフィルタ（例: {"joy": {"min": 10}, "anger": {"max": 50}}）
        limit: 取得件数上限（デフォルト: 20）
        offset: オフセット（デフォルト: 0）
    """
    return await recall_impl(
        query=query,
        tags=tags,
        speaker=speaker,
        project=project,
        topic_id=topic_id,
        date_from=date_from,
        date_to=date_to,
        emotion_filter=emotion_filter,
        limit=limit,
        offset=offset,
    )


@mcp.tool()
async def forget(
    message_id: int,
    reason: str | None = None,
) -> dict:
    """記憶を論理削除する。

    指定した記憶を論理削除する。物理削除は行わない。
    recall の検索結果からは除外される。

    Args:
        message_id: 削除対象のメッセージID
        reason: 削除理由
    """
    return await forget_impl(
        message_id=message_id,
        reason=reason,
    )


@mcp.tool()
async def topic_manage(
    action: str,
    topic_id: int | None = None,
    name: str | None = None,
    roles: list[str] | None = None,
    emotion: dict | None = None,
    session_id: int | None = None,
) -> dict:
    """トピック（議題）のCRUD操作を行う。

    トピックの作成・クローズ・再開・更新を行う。

    Args:
        action: "create" / "close" / "reopen" / "update"
        topic_id: トピックID（close/reopen/update時必須）
        name: トピック名（create時必須）
        roles: 役割名の配列（sparring, support, review, study, casual等）
        emotion: 感情値 {"joy": 0-255, "anger": 0-255, "sorrow": 0-255, "fun": 0-255}
        session_id: セッションIDとの紐付け
    """
    return await topic_manage_impl(
        action=action,
        topic_id=topic_id,
        name=name,
        roles=roles,
        emotion=emotion,
        session_id=session_id,
    )


@mcp.tool()
async def organize(
    message_ids: list[int] | None = None,
    query: list[str] | None = None,
    tags: list[str] | None = None,
    speaker: str | None = None,
    project: str | None = None,
    topic_id: list[int] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    emotion_filter: dict | None = None,
    include_deleted: bool = False,
    add_tags: list[str] | None = None,
    remove_tags: list[str] | None = None,
    limit: int = 100000,
) -> dict:
    """メッセージのタグ整理を行う。

    検索条件またはID直接指定で対象メッセージを特定し、
    タグの追加・削除を一括で行う。rememberからタグ付け責務を分離した専用コマンド。

    Args:
        message_ids: 対象メッセージIDの直接指定（検索条件との併用可）
        query: 全文検索キーワード（AND検索）
        tags: 既存タグでフィルタ（AND検索）
        speaker: 発言者でフィルタ
        project: プロジェクト名でフィルタ
        topic_id: トピックIDでフィルタ（OR検索）
        date_from: 日付範囲の開始（YYYY-MM-DD）
        date_to: 日付範囲の終了（YYYY-MM-DD）
        emotion_filter: 感情値のレンジフィルタ（例: {"joy": {"min": 10}, "anger": {"max": 50}}）
        include_deleted: 論理削除済みも対象にする（デフォルト: false）
        add_tags: 追加するタグ名の配列（未登録タグは自動作成）
        remove_tags: 削除するタグ名の配列
        limit: 処理件数上限（デフォルト: 100000）
    """
    return await organize_impl(
        message_ids=message_ids,
        query=query,
        tags=tags,
        speaker=speaker,
        project=project,
        topic_id=topic_id,
        date_from=date_from,
        date_to=date_to,
        emotion_filter=emotion_filter,
        include_deleted=include_deleted,
        add_tags=add_tags,
        remove_tags=remove_tags,
        limit=limit,
    )


@mcp.tool()
async def rulebook(
    action: str,
    key: str | None = None,
    content: str | None = None,
    reason: str | None = None,
    persona_id: str | None = None,
) -> dict:
    """ルールブックの参照・設定・廃止を行う。

    イミュータブル追記型で、バージョン管理される。
    最新かつ有効なルールのみを取得する。

    Args:
        action: "get" / "set" / "retire" / "list"
        key: ルールキー（例: "persona.tone", "format.code_review"）
        content: ルール本文（set時必須、Markdown）
        reason: 変更理由
        persona_id: ペルソナID（省略時は全ペルソナ共通 '*'）
    """
    return await rulebook_impl(
        action=action,
        key=key,
        content=content,
        reason=reason,
        persona_id=persona_id,
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
