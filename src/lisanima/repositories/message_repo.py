"""メッセージリポジトリ

messages テーブルへのCRUD操作を提供する。
"""
from psycopg import AsyncConnection, sql


def encodeEmotion(joy: int = 0, anger: int = 0, sorrow: int = 0, fun: int = 0) -> int:
    """感情ベクトルを4バイト整数にエンコードする。

    Args:
        joy: 喜び (0-255)
        anger: 怒り (0-255)
        sorrow: 哀しみ (0-255)
        fun: 楽しさ (0-255)

    Returns:
        符号付き32bit整数
    """
    for name, val in [("joy", joy), ("anger", anger), ("sorrow", sorrow), ("fun", fun)]:
        if not 0 <= val <= 255:
            raise ValueError(f"{name} は 0〜255 の範囲で指定してください: {val}")

    unsigned = (joy << 24) | (anger << 16) | (sorrow << 8) | fun
    # Pythonは任意精度整数なので、PostgreSQL互換の符号付き32bitに変換
    if unsigned >= 0x80000000:
        return unsigned - 0x100000000
    return unsigned


def decodeEmotion(emotion: int) -> dict:
    """4バイト整数から感情ベクトルをデコードする。

    Args:
        emotion: 符号付き32bit整数

    Returns:
        {"joy": int, "anger": int, "sorrow": int, "fun": int}
    """
    # 符号付き→符号なしに変換
    if emotion < 0:
        emotion += 0x100000000

    return {
        "joy": (emotion >> 24) & 0xFF,
        "anger": (emotion >> 16) & 0xFF,
        "sorrow": (emotion >> 8) & 0xFF,
        "fun": emotion & 0xFF,
    }


async def insertMessage(
    conn: AsyncConnection,
    session_id: int,
    category: str,
    speaker: str,
    content: str,
    emotion: int = 0,
    target: str | None = None,
) -> dict:
    """メッセージを保存する。

    Args:
        conn: DB接続
        session_id: セッションID
        category: 種別
        speaker: 発言者
        content: 発言内容
        emotion: 感情ベクトル（エンコード済み）
        target: 発言先

    Returns:
        保存したメッセージのdict
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO messages (session_id, category, speaker, content, emotion, target)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, session_id, category, speaker, target, content,
                      emotion, emotion_total, is_deleted, created_at
            """,
            (session_id, category, speaker, content, emotion, target),
        )
        return await cur.fetchone()


async def searchMessages(
    conn: AsyncConnection,
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
    """メッセージを検索する。

    Args:
        conn: DB接続
        query: 全文検索キーワード
        tags: タグ名フィルタ（AND検索）
        speaker: 発言者フィルタ
        category: 種別フィルタ
        date_from: 日付範囲開始（YYYY-MM-DD）
        date_to: 日付範囲終了（YYYY-MM-DD）
        min_emotion: 最低感情値合計
        limit: 取得件数上限
        offset: オフセット

    Returns:
        {"total": int, "messages": list[dict]}
    """
    # WHERE句の動的構築
    conditions = ["m.is_deleted = FALSE"]
    params: list = []

    if query:
        conditions.append("m.content ILIKE %s")
        params.append(f"%{query}%")

    if speaker:
        conditions.append("m.speaker = %s")
        params.append(speaker)

    if category:
        conditions.append("m.category = %s")
        params.append(category)

    if min_emotion is not None:
        conditions.append("m.emotion_total >= %s")
        params.append(min_emotion)

    if date_from:
        conditions.append("s.date >= %s")
        params.append(date_from)

    if date_to:
        conditions.append("s.date <= %s")
        params.append(date_to)

    # タグフィルタ（AND検索: 指定した全タグを持つメッセージのみ）
    tag_join = ""
    if tags:
        tag_join = """
            JOIN message_tags mt ON m.id = mt.message_id
            JOIN tags t ON mt.tag_id = t.id
        """
        placeholders = ", ".join(["%s"] * len(tags))
        conditions.append(f"t.name IN ({placeholders})")
        params.extend([t.lower().strip() for t in tags])

    where_clause = " AND ".join(conditions)

    # タグのAND検索: HAVING COUNT で全タグ一致を保証
    group_by = ""
    having = ""
    if tags:
        group_by = "GROUP BY m.id, s.date"
        having = f"HAVING COUNT(DISTINCT t.name) = {len(tags)}"

    # ORDER BY: query指定時はpg_trgm類似度、それ以外は新しい順
    if query:
        order_by = "ORDER BY similarity(m.content, %s) DESC, m.emotion_total DESC, m.created_at DESC"
        order_params = [query]
    else:
        order_by = "ORDER BY m.created_at DESC"
        order_params = []

    async with conn.cursor() as cur:
        # 件数取得
        count_sql = f"""
            SELECT COUNT(*) FROM (
                SELECT m.id
                FROM messages m
                JOIN sessions s ON m.session_id = s.id
                {tag_join}
                WHERE {where_clause}
                {group_by}
                {having}
            ) sub
        """
        await cur.execute(count_sql, params)
        total = (await cur.fetchone())["count"]

        # データ取得
        data_sql = f"""
            SELECT m.id, s.date AS session_date, m.category, m.speaker, m.target,
                   m.content, m.emotion, m.emotion_total, m.created_at
            FROM messages m
            JOIN sessions s ON m.session_id = s.id
            {tag_join}
            WHERE {where_clause}
            {group_by}
            {having}
            {order_by}
            LIMIT %s OFFSET %s
        """
        await cur.execute(data_sql, params + order_params + [limit, offset])
        rows = await cur.fetchall()

    # 感情値をデコードして返す
    messages = []
    for row in rows:
        msg = dict(row)
        msg["emotion"] = decodeEmotion(msg["emotion"])
        # タグ情報を付与
        msg["tags"] = await _getMessageTags(conn, msg["id"])
        messages.append(msg)

    return {"total": total, "messages": messages}


async def _getMessageTags(conn: AsyncConnection, message_id: int) -> list[str]:
    """メッセージに紐づくタグ名のリストを取得する。"""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT t.name FROM tags t
            JOIN message_tags mt ON t.id = mt.tag_id
            WHERE mt.message_id = %s
            ORDER BY t.name
            """,
            (message_id,),
        )
        return [row["name"] for row in await cur.fetchall()]
