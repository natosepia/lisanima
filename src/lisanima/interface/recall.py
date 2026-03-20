"""recall ツール — 記憶を検索する"""
import logging
from datetime import date

from lisanima.db import db_pool
from lisanima.repositories import message_repo
from lisanima.repositories._validators import parseDateRange, validateEmotionFilter

logger = logging.getLogger(__name__)


def _validateParams(
    limit: int,
    offset: int,
    date_from: str | None,
    date_to: str | None,
    emotion_filter: dict | None = None,
) -> tuple[date | None, date | None, str | None]:
    """入力パラメータを検証する。

    Args:
        limit: 取得件数上限
        offset: オフセット
        date_from: 日付範囲開始
        date_to: 日付範囲終了
        emotion_filter: 感情レンジフィルタ

    Returns:
        (parsed_date_from, parsed_date_to, エラーなしならNone)

    Raises:
        ValueError: バリデーションエラー時
    """
    if limit < 1:
        raise ValueError("limit は 1 以上で指定してください")

    if offset < 0:
        raise ValueError("offset は 0 以上で指定してください")

    parsed_from, parsed_to = parseDateRange(date_from, date_to)
    validateEmotionFilter(emotion_filter)

    return parsed_from, parsed_to, None


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

    Args:
        query: 全文検索キーワード（AND検索）
        tags: タグ名でフィルタ（AND検索）
        speaker: 発言者でフィルタ
        project: プロジェクト名でフィルタ
        topic_id: トピックIDでフィルタ（OR検索）
        date_from: 日付範囲の開始（YYYY-MM-DD）
        date_to: 日付範囲の終了（YYYY-MM-DD）
        emotion_filter: 感情値のレンジフィルタ
        limit: 取得件数上限（デフォルト: 20）
        offset: オフセット（デフォルト: 0）

    Returns:
        {"total": int, "messages": list[dict]}
        エラー時は {"error": "ERROR_CODE", "message": "エラーメッセージ"}
    """
    # バリデーション
    try:
        _validateParams(limit, offset, date_from, date_to, emotion_filter)
    except ValueError as e:
        return {"error": "INVALID_PARAMETER", "message": str(e)}

    try:
        async with db_pool.get_connection() as conn:
            result = await message_repo.searchMessages(
                conn,
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
