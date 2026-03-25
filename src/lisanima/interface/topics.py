"""topic_manage ツール — トピックCRUD"""
import logging

from lisanima.db import db_pool
from lisanima.repositories import topic_repo
from lisanima.repositories._validators import validateEmotion

logger = logging.getLogger(__name__)

# 許可するアクション
_VALID_ACTIONS = {"create", "close", "reopen", "update", "list"}


def _validateParams(
    action: str,
    topic_id: int | None,
    name: str | None,
    emotion: dict | None,
    add_message_ids: list[int] | None = None,
    remove_message_ids: list[int] | None = None,
) -> None:
    """入力パラメータを検証する。

    Args:
        action: アクション文字列
        topic_id: トピックID
        name: トピック名
        emotion: 感情値辞書
        add_message_ids: 追加するメッセージIDリスト
        remove_message_ids: 削除するメッセージIDリスト

    Raises:
        ValueError: バリデーションエラー時
    """
    if action not in _VALID_ACTIONS:
        raise ValueError("action は create/close/reopen/update/list のいずれかです")

    if action == "create":
        if not name or not name.strip():
            raise ValueError("create 時は name が必須です")

    if action in ("close", "reopen", "update"):
        if topic_id is None:
            raise ValueError(f"{action} 時は topic_id が必須です")

    # add_message_ids と remove_message_ids の重複チェック
    if add_message_ids and remove_message_ids:
        overlap = set(add_message_ids) & set(remove_message_ids)
        if overlap:
            raise ValueError(
                f"add_message_ids と remove_message_ids に同一IDがあります: {sorted(overlap)}"
            )

    validateEmotion(emotion)


async def topicManage(
    action: str,
    topic_id: int | None = None,
    name: str | None = None,
    emotion: dict | None = None,
    message_ids: list[int] | None = None,
    add_message_ids: list[int] | None = None,
    remove_message_ids: list[int] | None = None,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """トピックの作成・クローズ・再開・更新・一覧取得を行う。

    Args:
        action: "create" / "close" / "reopen" / "update" / "list"
        topic_id: トピックID（close/reopen/update時必須）
        name: トピック名（create時必須）
        emotion: 感情値 {"joy": 0-255, "anger": 0-255, "sorrow": 0-255, "fun": 0-255}
        message_ids: メッセージIDリスト（create時の初期紐付け）
        add_message_ids: 追加するメッセージIDリスト（update時）
        remove_message_ids: 削除するメッセージIDリスト（update時）
        status_filter: ステータスフィルタ（list時: "open" / "closed"）
        limit: 取得件数上限（list時、デフォルト: 50）
        offset: オフセット（list時、デフォルト: 0）

    Returns:
        アクション結果のdict
        エラー時は {"error": "ERROR_CODE", "message": "エラーメッセージ"}
    """
    # バリデーション
    try:
        _validateParams(action, topic_id, name, emotion, add_message_ids, remove_message_ids)
    except ValueError as e:
        return {"error": "INVALID_PARAMETER", "message": str(e)}

    try:
        async with db_pool.get_connection() as conn:
            async with conn.transaction():
                if action == "list":
                    return await _handleList(conn, status_filter, limit, offset)
                elif action == "create":
                    return await _handleCreate(conn, name, emotion, message_ids)
                elif action == "close":
                    return await _handleClose(conn, topic_id)
                elif action == "reopen":
                    return await _handleReopen(conn, topic_id)
                else:  # update
                    return await _handleUpdate(
                        conn, topic_id, name, emotion, add_message_ids, remove_message_ids,
                    )

    except RuntimeError as e:
        logger.error("DB接続エラー: %s", e)
        return {"error": "DB_CONNECTION_ERROR", "message": str(e)}
    except Exception:
        logger.error("topicManage failed", exc_info=True)
        return {"error": "INTERNAL_ERROR", "message": "予期しないエラーが発生しました"}


async def _handleList(
    conn,
    status_filter: str | None,
    limit: int,
    offset: int,
) -> dict:
    """listアクションの処理。

    Args:
        conn: DB接続
        status_filter: ステータスフィルタ
        limit: 取得件数上限
        offset: オフセット

    Returns:
        トピック一覧のdict
    """
    result = await topic_repo.listTopics(
        conn, status=status_filter, limit=limit, offset=offset,
    )

    # datetimeをISO文字列に変換
    for topic in result["topics"]:
        if topic.get("created_at"):
            topic["created_at"] = topic["created_at"].isoformat()
        if topic.get("closed_at"):
            topic["closed_at"] = topic["closed_at"].isoformat()

    logger.debug("topic_manage list完了: total=%d", result["total"])
    return result


async def _handleCreate(
    conn,
    name: str,
    emotion: dict | None,
    message_ids: list[int] | None,
) -> dict:
    """createアクションの処理。

    Args:
        conn: DB接続
        name: トピック名
        emotion: 感情値辞書
        message_ids: 紐付けるメッセージIDリスト

    Returns:
        作成結果のdict
    """
    topic = await topic_repo.createTopic(
        conn,
        name=name,
        emotion=emotion,
        message_ids=message_ids,
    )

    logger.debug("topic_manage create完了: topic_id=%s", topic["id"])

    return {
        "topic_id": topic["id"],
        "name": topic["name"],
        "status": topic["status"],
        "message_count": topic.get("message_count", 0),
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
    emotion: dict | None,
    add_message_ids: list[int] | None,
    remove_message_ids: list[int] | None,
) -> dict:
    """updateアクションの処理。

    Args:
        conn: DB接続
        topic_id: トピックID
        name: トピック名（部分更新）
        emotion: 感情値辞書（部分更新）
        add_message_ids: 紐付け追加するメッセージIDリスト
        remove_message_ids: 紐付け削除するメッセージIDリスト

    Returns:
        更新結果のdict
    """
    result = await topic_repo.updateTopic(
        conn,
        topic_id=topic_id,
        name=name,
        emotion=emotion,
        add_message_ids=add_message_ids,
        remove_message_ids=remove_message_ids,
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
        "message_count": result.get("message_count", 0),
    }
