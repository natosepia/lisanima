"""edit ツール — 既存メッセージの content / emotion を部分修正する"""
import logging

from lisanima.db import db_pool
from lisanima.repositories import message_repo
from lisanima.repositories._validators import validateEmotion

logger = logging.getLogger(__name__)


async def edit(
    message_id: int,
    content: str | None = None,
    emotion: dict | None = None,
    reason: str | None = None,
) -> dict:
    """既存メッセージの content / emotion を部分修正する。

    直接UPDATEで、バージョン管理は行わない。

    Args:
        message_id: 対象メッセージID
        content: 新しい内容（指定時のみ更新）
        emotion: 新しい感情値（{joy, anger, sorrow, fun} 各0-255、指定キーのみ更新）
        reason: 編集理由（記録用。現在はログ出力のみ）

    Returns:
        {"message_id": int, "status": "edited"}
        エラー時は {"error": "ERROR_CODE", "message": "エラーメッセージ"}
    """
    # message_id バリデーション
    if not isinstance(message_id, int) or message_id <= 0:
        return {
            "error": "INVALID_PARAMETER",
            "message": f"message_id は正の整数で指定してください: {message_id}",
        }

    # content と emotion の両方省略チェック
    if content is None and emotion is None:
        return {
            "error": "INVALID_PARAMETER",
            "message": "content または emotion のいずれかを指定してください",
        }

    # content が空文字列の場合を拒否
    if content is not None and not content.strip():
        return {
            "error": "INVALID_PARAMETER",
            "message": "content は空にできません",
        }

    # emotion バリデーション
    try:
        validateEmotion(emotion)
    except ValueError as e:
        return {"error": "INVALID_PARAMETER", "message": str(e)}

    if reason:
        logger.info("edit reason: message_id=%s, reason=%s", message_id, reason)

    try:
        async with db_pool.get_connection() as conn:
            async with conn.transaction():
                result = await message_repo.editMessage(
                    conn,
                    message_id=message_id,
                    content=content,
                    emotion=emotion,
                )

        if result is None:
            return {
                "error": "NOT_FOUND",
                "message": f"指定されたメッセージが見つかりません（id: {message_id}）",
            }

        logger.debug("edit完了: message_id=%s", message_id)
        return {
            "message_id": result["id"],
            "status": "edited",
        }

    except RuntimeError as e:
        logger.error("DB接続エラー: %s", e)
        return {"error": "DB_CONNECTION_ERROR", "message": str(e)}
    except Exception as e:
        logger.error("edit failed", exc_info=True)
        return {"error": "INTERNAL_ERROR", "message": "予期しないエラーが発生しました"}
