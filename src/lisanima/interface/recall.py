"""recall ツール — 記憶を検索する"""
import logging
from datetime import date

from lisanima.db import db_pool
from lisanima.repositories import message_repo

logger = logging.getLogger(__name__)


def _validateParams(
    limit: int,
    offset: int,
    date_from: str | None,
    date_to: str | None,
) -> tuple[date | None, date | None, str | None]:
    """入力パラメータを検証する。

    Args:
        limit: 取得件数上限
        offset: オフセット
        date_from: 日付範囲開始
        date_to: 日付範囲終了

    Returns:
        (parsed_date_from, parsed_date_to, エラーなしならNone)

    Raises:
        ValueError: バリデーションエラー時
    """
    if limit < 1:
        raise ValueError("limit は 1 以上で指定してください")

    if offset < 0:
        raise ValueError("offset は 0 以上で指定してください")

    parsed_from = None
    parsed_to = None

    if date_from:
        try:
            parsed_from = date.fromisoformat(date_from)
        except ValueError:
            raise ValueError(f"date_from の形式が不正です（YYYY-MM-DD）: {date_from}")

    if date_to:
        try:
            parsed_to = date.fromisoformat(date_to)
        except ValueError:
            raise ValueError(f"date_to の形式が不正です（YYYY-MM-DD）: {date_to}")

    if parsed_from and parsed_to and parsed_from > parsed_to:
        raise ValueError(
            f"date_from({date_from}) が date_to({date_to}) より後になっています"
        )

    return parsed_from, parsed_to, None


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

    Args:
        query: 全文検索キーワード
        tags: タグ名でフィルタ（AND検索）
        speaker: 発言者でフィルタ
        date_from: 日付範囲の開始（YYYY-MM-DD）
        date_to: 日付範囲の終了（YYYY-MM-DD）
        min_emotion: 感情値合計の下限
        limit: 取得件数上限（デフォルト: 20）
        offset: オフセット（デフォルト: 0）

    Returns:
        {"total": int, "messages": list[dict]}
        エラー時は {"error": "ERROR_CODE", "message": "エラーメッセージ"}
    """
    # バリデーション
    try:
        _validateParams(limit, offset, date_from, date_to)
    except ValueError as e:
        return {"error": "INVALID_PARAMETER", "message": str(e)}

    try:
        async with db_pool.get_connection() as conn:
            result = await message_repo.searchMessages(
                conn,
                query=query,
                tags=tags,
                speaker=speaker,
                date_from=date_from,
                date_to=date_to,
                min_emotion=min_emotion,
                limit=limit,
                offset=offset,
            )

        # datetimeをISO文字列に変換
        for msg in result["messages"]:
            if msg.get("created_at"):
                msg["created_at"] = msg["created_at"].isoformat()
            if msg.get("session_date"):
                msg["session_date"] = str(msg["session_date"])

        logger.debug("recall完了: total=%d", result["total"])
        return result

    except RuntimeError as e:
        logger.error("DB接続エラー: %s", e)
        return {"error": "DB_CONNECTION_ERROR", "message": str(e)}
    except Exception as e:
        logger.error("recall failed", exc_info=True)
        return {"error": "INTERNAL_ERROR", "message": "予期しないエラーが発生しました"}
