"""remember ツール — 記憶を保存する"""
from datetime import date

from lisanima.db import db_pool
from lisanima.repositories import session_repo, message_repo, tag_repo


async def remember(
    content: str,
    speaker: str,
    category: str = "session",
    target: str | None = None,
    emotion: dict | None = None,
    tags: list[str] | None = None,
    project: str | None = None,
    session_date: str | None = None,
) -> dict:
    """記憶を保存する。

    Args:
        content: 発言・記憶の内容
        speaker: 発言者名
        category: 種別（session / backlog / knowledge / discussion / report）
        target: 発言先
        emotion: 感情値 {"joy": 0-255, "anger": 0-255, "sorrow": 0-255, "fun": 0-255}
        tags: タグ名の配列
        project: プロジェクト名
        session_date: セッション日付 YYYY-MM-DD

    Returns:
        {"message_id": int, "session_id": int, "tags_created": list, "status": "saved"}
    """
    # 日付パース
    target_date = date.fromisoformat(session_date) if session_date else date.today()

    # 感情値エンコード
    emo = emotion or {}
    emotion_encoded = message_repo.encodeEmotion(
        joy=emo.get("joy", 0),
        anger=emo.get("anger", 0),
        sorrow=emo.get("sorrow", 0),
        fun=emo.get("fun", 0),
    )

    async with db_pool.get_connection() as conn:
        # セッション取得or作成
        session = await session_repo.findOrCreateSession(
            conn, target_date, project=project,
        )

        # メッセージ保存
        message = await message_repo.insertMessage(
            conn,
            session_id=session["id"],
            category=category,
            speaker=speaker,
            content=content,
            emotion=emotion_encoded,
            target=target,
        )

        # タグ処理
        tags_created = []
        if tags:
            tag_records = await tag_repo.findOrCreateTags(conn, tags)
            tag_ids = [t["id"] for t in tag_records]
            await tag_repo.linkMessageTags(conn, message["id"], tag_ids)
            tags_created = [t["name"] for t in tag_records]

        await conn.commit()

    return {
        "message_id": message["id"],
        "session_id": session["id"],
        "tags_created": tags_created,
        "status": "saved",
    }
