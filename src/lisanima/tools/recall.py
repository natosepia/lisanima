"""recall ツール — 記憶を検索する"""
from lisanima.db import db_pool
from lisanima.repositories import message_repo


async def recall(
    query: str | None = None,
    tags: list[str] | None = None,
    speaker: str | None = None,
    category: str | None = None,
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
        category: 種別でフィルタ
        date_from: 日付範囲の開始（YYYY-MM-DD）
        date_to: 日付範囲の終了（YYYY-MM-DD）
        min_emotion: 感情値合計の下限
        limit: 取得件数上限（デフォルト: 20）
        offset: オフセット（デフォルト: 0）

    Returns:
        {"total": int, "messages": list[dict]}
    """
    async with db_pool.get_connection() as conn:
        result = await message_repo.searchMessages(
            conn,
            query=query,
            tags=tags,
            speaker=speaker,
            category=category,
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

    return result
