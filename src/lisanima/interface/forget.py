"""forget ツール — 記憶を論理削除する"""
import logging

from lisanima.db import db_pool
from lisanima.repositories import message_repo

logger = logging.getLogger(__name__)


async def forget(message_id: int, reason: str | None = None) -> dict:
    """指定した記憶を論理削除する。物理削除は行わない。

    Args:
        message_id: 削除対象のメッセージID
        reason: 削除理由（省略時は "none"）

    Returns:
        {"message_id": int, "status": "forgotten"}
        エラー時は {"error": "ERROR_CODE", "message": "エラーメッセージ"}
    """
    # バリデーション
    if not isinstance(message_id, int) or message_id <= 0:
        return {
            "error": "INVALID_PARAMETER",
            "message": f"message_id は正の整数で指定してください: {message_id}",
        }

    delete_reason = reason if reason else "none"

    try:
        async with db_pool.get_connection() as conn:
            async with conn.transaction():
                result = await message_repo.softDelete(
                    conn, message_id, reason=delete_reason,
                )

        if result is None:
            return {
                "error": "NOT_FOUND",
                "message": f"指定されたメッセージが見つかりません（id: {message_id}）",
            }

        logger.debug("forget完了: message_id=%s", message_id)
        return {
            "message_id": result["id"],
            "status": "forgotten",
        }

    except RuntimeError as e:
        logger.error("DB接続エラー: %s", e)
        return {"error": "DB_CONNECTION_ERROR", "message": str(e)}
    except Exception as e:
        logger.error("forget failed", exc_info=True)
        return {"error": "INTERNAL_ERROR", "message": "予期しないエラーが発生しました"}
