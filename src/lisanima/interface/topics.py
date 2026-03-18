"""topic_manage ツール — トピックCRUD"""
import logging

from lisanima.db import db_pool
from lisanima.repositories import topic_repo

logger = logging.getLogger(__name__)

# 許可するアクション
_VALID_ACTIONS = {"create", "close", "reopen", "update"}

# 感情値として許可するキー
_VALID_EMOTION_KEYS = {"joy", "anger", "sorrow", "fun"}


def _validateEmotion(emotion: dict | None) -> None:
    """感情値辞書を検証する。

    Args:
        emotion: 感情値辞書

    Raises:
        ValueError: 不正なキーまたは値の場合
    """
    if not emotion:
        return

    invalid_keys = set(emotion.keys()) - _VALID_EMOTION_KEYS
    if invalid_keys:
        raise ValueError(f"emotion に不正なキーがあります: {invalid_keys}")

    for key, val in emotion.items():
        if not isinstance(val, int) or not (0 <= val <= 255):
            raise ValueError(f"emotion.{key} は 0〜255 の整数で指定してください: {val}")


def _validateParams(
    action: str,
    topic_id: int | None,
    name: str | None,
    emotion: dict | None,
) -> None:
    """入力パラメータを検証する。

    Args:
        action: アクション文字列
        topic_id: トピックID
        name: トピック名
        emotion: 感情値辞書

    Raises:
        ValueError: バリデーションエラー時
    """
    if action not in _VALID_ACTIONS:
        raise ValueError("action は create/close/reopen/update のいずれかです")

    if action == "create":
        if not name or not name.strip():
            raise ValueError("create 時は name が必須です")

    if action in ("close", "reopen", "update"):
        if topic_id is None:
            raise ValueError(f"{action} 時は topic_id が必須です")

    _validateEmotion(emotion)


async def topicManage(
    action: str,
    topic_id: int | None = None,
    name: str | None = None,
    roles: list[str] | None = None,
    emotion: dict | None = None,
    session_id: int | None = None,
) -> dict:
    """トピックの作成・クローズ・再開・更新を行う。

    Args:
        action: "create" / "close" / "reopen" / "update"
        topic_id: トピックID（close/reopen/update時必須）
        name: トピック名（create時必須）
        roles: 役割名の配列
        emotion: 感情値 {"joy": 0-255, "anger": 0-255, "sorrow": 0-255, "fun": 0-255}
        session_id: セッションIDとの紐付け

    Returns:
        アクション結果のdict
        エラー時は {"error": "ERROR_CODE", "message": "エラーメッセージ"}
    """
    # バリデーション
    try:
        _validateParams(action, topic_id, name, emotion)
    except ValueError as e:
        return {"error": "INVALID_PARAMETER", "message": str(e)}

    try:
        async with db_pool.get_connection() as conn:
            async with conn.transaction():
                if action == "create":
                    return await _handleCreate(conn, name, roles, emotion, session_id)
                elif action == "close":
                    return await _handleClose(conn, topic_id)
                elif action == "reopen":
                    return await _handleReopen(conn, topic_id)
                else:  # update
                    return await _handleUpdate(conn, topic_id, name, roles, emotion)

    except RuntimeError as e:
        logger.error("DB接続エラー: %s", e)
        return {"error": "DB_CONNECTION_ERROR", "message": str(e)}
    except Exception:
        logger.error("topicManage failed", exc_info=True)
        return {"error": "INTERNAL_ERROR", "message": "予期しないエラーが発生しました"}


async def _handleCreate(
    conn,
    name: str,
    roles: list[str] | None,
    emotion: dict | None,
    session_id: int | None,
) -> dict:
    """createアクションの処理。

    Args:
        conn: DB接続
        name: トピック名
        roles: 役割名の配列
        emotion: 感情値辞書
        session_id: セッションID

    Returns:
        作成結果のdict
    """
    topic = await topic_repo.createTopic(
        conn,
        name=name,
        emotion=emotion,
        roles=roles,
        session_id=session_id,
    )

    logger.debug("topic_manage create完了: topic_id=%s", topic["id"])

    return {
        "topic_id": topic["id"],
        "name": topic["name"],
        "status": topic["status"],
        "roles": topic["roles"],
    }


async def _handleClose(conn, topic_id: int) -> dict:
    """closeアクションの処理。

    Args:
        conn: DB接続
        topic_id: トピックID

    Returns:
        クローズ結果のdict
    """
    result = await topic_repo.closeTopic(conn, topic_id)
    if not result:
        return {
            "error": "NOT_FOUND",
            "message": f"トピック(id={topic_id})が存在しないか、既にクローズされています",
        }

    logger.debug("topic_manage close完了: topic_id=%s", topic_id)
    return {"topic_id": topic_id, "status": "closed"}


async def _handleReopen(conn, topic_id: int) -> dict:
    """reopenアクションの処理。

    Args:
        conn: DB接続
        topic_id: トピックID

    Returns:
        再オープン結果のdict
    """
    result = await topic_repo.reopenTopic(conn, topic_id)
    if not result:
        return {
            "error": "NOT_FOUND",
            "message": f"トピック(id={topic_id})が存在しないか、既にオープンされています",
        }

    logger.debug("topic_manage reopen完了: topic_id=%s", topic_id)
    return {"topic_id": topic_id, "status": "open"}


async def _handleUpdate(
    conn,
    topic_id: int,
    name: str | None,
    roles: list[str] | None,
    emotion: dict | None,
) -> dict:
    """updateアクションの処理。

    Args:
        conn: DB接続
        topic_id: トピックID
        name: トピック名（部分更新）
        roles: 役割名の配列（指定時は洗い替え）
        emotion: 感情値辞書（部分更新）

    Returns:
        更新結果のdict
    """
    result = await topic_repo.updateTopic(
        conn,
        topic_id=topic_id,
        name=name,
        emotion=emotion,
        roles=roles,
    )
    if not result:
        return {
            "error": "NOT_FOUND",
            "message": f"トピック(id={topic_id})が存在しません",
        }

    logger.debug("topic_manage update完了: topic_id=%s", topic_id)

    return {
        "topic_id": result["id"],
        "name": result["name"],
        "status": result["status"],
        "roles": result["roles"],
    }
