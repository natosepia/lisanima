"""remember ツール — 記憶を保存する"""
import logging
from datetime import date

from lisanima.db import db_pool
from lisanima.repositories import session_repo, message_repo, topic_repo, role_repo
from lisanima.repositories._validators import validateEmotion

logger = logging.getLogger(__name__)


def _validateParams(
    content: str,
    speaker: str,
    session_date: str | None,
    emotion: dict | None,
) -> tuple[date, str | None]:
    """入力パラメータを検証する。

    Args:
        content: 発言内容
        speaker: 発言者名
        session_date: セッション日付文字列
        emotion: 感情値辞書

    Returns:
        (パース済みdate, エラーなしならNone) のタプル

    Raises:
        ValueError: バリデーションエラー時（messageフィールドにエラー内容）
    """
    if not content or not content.strip():
        raise ValueError("content は空にできません")

    if not speaker or not speaker.strip():
        raise ValueError("speaker は空にできません")

    # 日付パース
    target_date = date.today()
    if session_date:
        try:
            target_date = date.fromisoformat(session_date)
        except ValueError:
            raise ValueError(f"session_date の形式が不正です（YYYY-MM-DD）: {session_date}")

    # 感情値バリデーション
    validateEmotion(emotion)

    return target_date, None


async def remember(
    content: str,
    speaker: str,
    target: str | None = None,
    emotion: dict | None = None,
    topic_id: int | None = None,
    project: str | None = None,
    session_date: str | None = None,
    source: str = "unknown",
    roles: list[str] | None = None,
) -> dict:
    """記憶を保存する。

    Args:
        content: 発言・記憶の内容
        speaker: 発言者名
        target: 発言先
        emotion: 感情値 {"joy": 0-255, "anger": 0-255, "sorrow": 0-255, "fun": 0-255}
        topic_id: トピックID（指定時はメッセージとトピックの紐付けも自動作成）
        project: プロジェクト名
        session_date: セッション日付 YYYY-MM-DD
        source: MCPクライアント識別子
        roles: 役割名の配列（指定時はメッセージとロールの紐付けを自動作成）

    Returns:
        {"message_id": int, "session_id": int, "status": "saved"}
        エラー時は {"error": "ERROR_CODE", "message": "エラーメッセージ"}
    """
    # バリデーション
    try:
        target_date, _ = _validateParams(content, speaker, session_date, emotion)
    except ValueError as e:
        return {"error": "INVALID_PARAMETER", "message": str(e)}

    # topic_id バリデーション
    if topic_id is not None:
        if not isinstance(topic_id, int) or topic_id <= 0:
            return {
                "error": "INVALID_PARAMETER",
                "message": "topic_id は正の整数で指定してください",
            }

    emo = emotion or {}

    try:
        async with db_pool.get_connection() as conn:
            async with conn.transaction():
                # セッション取得or作成
                session = await session_repo.findOrCreateSession(
                    conn, target_date, project=project,
                )

                # メッセージ保存
                message = await message_repo.insertMessage(
                    conn,
                    session_id=session["id"],
                    speaker=speaker,
                    content=content,
                    joy=emo.get("joy", 0),
                    anger=emo.get("anger", 0),
                    sorrow=emo.get("sorrow", 0),
                    fun=emo.get("fun", 0),
                    target=target,
                    source=source,
                )

                # トピック紐付け（メッセージ単位）
                if topic_id is not None:
                    topic = await topic_repo.getTopicById(conn, topic_id)
                    if not topic:
                        raise LookupError(
                            f"指定されたトピックが見つかりません（id: {topic_id}）"
                        )
                    await topic_repo.linkMessageTopics(conn, [message["id"]], topic_id)

                # ロール紐付け
                if roles:
                    role_records = await role_repo.findOrCreateRoles(conn, roles)
                    await role_repo.linkMessageRoles(
                        conn, message["id"], [r["id"] for r in role_records],
                    )

        logger.debug(
            "remember完了: message_id=%s, session_id=%s",
            message["id"], session["id"],
        )

        return {
            "message_id": message["id"],
            "session_id": session["id"],
            "emotion_total": message["emotion_total"],
            "status": "saved",
        }

    except LookupError as e:
        return {"error": "NOT_FOUND", "message": str(e)}
    except RuntimeError as e:
        logger.error("DB接続エラー: %s", e)
        return {"error": "DB_CONNECTION_ERROR", "message": str(e)}
    except Exception as e:
        logger.error("remember failed", exc_info=True)
        return {"error": "INTERNAL_ERROR", "message": "予期しないエラーが発生しました"}
