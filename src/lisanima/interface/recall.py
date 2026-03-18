"""recall ツール — 記憶を検索する"""
import logging
from datetime import date

from lisanima.db import db_pool
from lisanima.repositories import message_repo

logger = logging.getLogger(__name__)

# emotion_filter で許可する感情軸
_VALID_EMOTION_AXES = {"joy", "anger", "sorrow", "fun"}


def _validateEmotionFilter(emotion_filter: dict) -> None:
    """emotion_filter の構造を検証する。

    Args:
        emotion_filter: 感情レンジフィルタ

    Raises:
        ValueError: キーや値が不正な場合
    """
    for axis, range_spec in emotion_filter.items():
        if axis not in _VALID_EMOTION_AXES:
            raise ValueError(
                f"emotion_filter のキーが不正です: '{axis}'（許可: {', '.join(sorted(_VALID_EMOTION_AXES))}）"
            )
        if not isinstance(range_spec, dict):
            raise ValueError(f"emotion_filter['{axis}'] は辞書で指定してください")

        for bound_key, bound_val in range_spec.items():
            if bound_key not in ("min", "max"):
                raise ValueError(
                    f"emotion_filter['{axis}'] に不正なキー '{bound_key}'（許可: min, max）"
                )
            if not isinstance(bound_val, int) or bound_val < 0 or bound_val > 255:
                raise ValueError(
                    f"emotion_filter['{axis}']['{bound_key}'] は 0-255 の整数で指定してください: {bound_val}"
                )

        # min > max の矛盾チェック
        if "min" in range_spec and "max" in range_spec:
            if range_spec["min"] > range_spec["max"]:
                raise ValueError(
                    f"emotion_filter['{axis}'] の min({range_spec['min']}) が max({range_spec['max']}) より大きいです"
                )


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

    if emotion_filter:
        _validateEmotionFilter(emotion_filter)

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
