"""トピックリポジトリ

t_topics / t_message_topics テーブルへのCRUD操作を提供する。
"""
import logging

from psycopg import AsyncConnection

from lisanima.repositories._validators import validateEmotion

logger = logging.getLogger(__name__)


async def linkMessageTopics(
    conn: AsyncConnection,
    message_ids: list[int],
    topic_id: int,
) -> int:
    """メッセージ群をトピックに紐付ける。

    Args:
        conn: DB接続
        message_ids: メッセージIDリスト
        topic_id: トピックID

    Returns:
        挿入行数
    """
    if not message_ids:
        return 0

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO t_message_topics (message_id, topic_id)
            SELECT m_id, %s
            FROM unnest(%s::int[]) AS m_id
            ON CONFLICT DO NOTHING
            """,
            (topic_id, message_ids),
        )
        inserted = cur.rowcount
        logger.debug(
            "メッセージ-トピック紐付け: topic_id=%s, messages=%d, inserted=%d",
            topic_id, len(message_ids), inserted,
        )
        return inserted


async def unlinkMessageTopics(
    conn: AsyncConnection,
    message_ids: list[int],
    topic_id: int,
) -> int:
    """メッセージ群からトピックの紐付けを削除する。

    Args:
        conn: DB接続
        message_ids: メッセージIDリスト
        topic_id: トピックID

    Returns:
        削除行数
    """
    if not message_ids:
        return 0

    async with conn.cursor() as cur:
        await cur.execute(
            """
            DELETE FROM t_message_topics
            WHERE message_id = ANY(%s) AND topic_id = %s
            """,
            (message_ids, topic_id),
        )
        deleted = cur.rowcount
        logger.debug(
            "メッセージ-トピック紐付け削除: topic_id=%s, messages=%d, deleted=%d",
            topic_id, len(message_ids), deleted,
        )
        return deleted


async def listTopics(
    conn: AsyncConnection,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """トピック一覧を取得する。

    Args:
        conn: DB接続
        status: フィルタ（"open" / "closed" / None=全件）
        limit: 取得件数上限
        offset: オフセット

    Returns:
        {"total": int, "topics": list[dict]}
    """
    conditions: list[str] = []
    params: list = []

    if status is not None:
        conditions.append("t.status = %s")
        params.append(status)

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    async with conn.cursor() as cur:
        # 件数取得
        await cur.execute(
            f"SELECT COUNT(*) FROM t_topics t WHERE {where_clause}",
            params,
        )
        total = (await cur.fetchone())["count"]

        # データ取得
        await cur.execute(
            f"""
            SELECT t.id AS topic_id, t.name, t.status,
                   t.joy, t.anger, t.sorrow, t.fun, t.emotion_total,
                   COUNT(mt.message_id) AS message_count,
                   t.created_at, t.closed_at
            FROM t_topics t
            LEFT JOIN t_message_topics mt ON t.id = mt.topic_id
            WHERE {where_clause}
            GROUP BY t.id
            ORDER BY t.created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = await cur.fetchall()

    topics = []
    for row in rows:
        topic = dict(row)
        topic["emotion"] = {
            "joy": topic.pop("joy"),
            "anger": topic.pop("anger"),
            "sorrow": topic.pop("sorrow"),
            "fun": topic.pop("fun"),
        }
        topics.append(topic)

    return {"total": total, "topics": topics}


async def createTopic(
    conn: AsyncConnection,
    name: str,
    emotion: dict[str, int] | None = None,
    message_ids: list[int] | None = None,
) -> dict:
    """トピックを作成する。

    Args:
        conn: DB接続
        name: トピック名
        emotion: 感情値 {"joy": int, "anger": int, "sorrow": int, "fun": int}
        message_ids: 紐付けるメッセージIDリスト

    Returns:
        作成したトピックのdict（message_count含む）
    """
    # 感情値のキー・値域チェック
    validateEmotion(emotion)

    em = emotion or {}
    joy = em.get("joy", 0)
    anger = em.get("anger", 0)
    sorrow = em.get("sorrow", 0)
    fun = em.get("fun", 0)

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO t_topics (name, joy, anger, sorrow, fun)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (name, joy, anger, sorrow, fun),
        )
        topic = await cur.fetchone()

    topic_id = topic["id"]
    logger.debug("トピック作成: id=%s, name=%s", topic_id, name)

    # メッセージ紐付け
    message_count = 0
    if message_ids:
        message_count = await linkMessageTopics(conn, message_ids, topic_id)

    result = dict(topic)
    result["message_count"] = message_count
    return result


async def closeTopic(
    conn: AsyncConnection,
    topic_id: int,
) -> dict | None:
    """トピックをクローズする。

    status='closed', closed_at=NOW() に更新する。
    存在しない場合、または既にclosedの場合はNoneを返す。

    Args:
        conn: DB接続
        topic_id: トピックID

    Returns:
        更新後のトピックdict、対象外の場合はNone
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE t_topics
            SET status = 'closed', closed_at = NOW()
            WHERE id = %s AND status = 'open'
            RETURNING *
            """,
            (topic_id,),
        )
        result = await cur.fetchone()

    if result:
        logger.debug("トピッククローズ: id=%s", topic_id)
    else:
        logger.debug("トピッククローズ対象外: id=%s（未検出 or 既にclosed）", topic_id)
    return result


async def reopenTopic(
    conn: AsyncConnection,
    topic_id: int,
) -> dict | None:
    """トピックを再オープンする。

    status='open', closed_at=NULL に更新する。
    存在しない場合、または既にopenの場合はNoneを返す。

    Args:
        conn: DB接続
        topic_id: トピックID

    Returns:
        更新後のトピックdict、対象外の場合はNone
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE t_topics
            SET status = 'open', closed_at = NULL
            WHERE id = %s AND status = 'closed'
            RETURNING *
            """,
            (topic_id,),
        )
        result = await cur.fetchone()

    if result:
        logger.debug("トピック再オープン: id=%s", topic_id)
    else:
        logger.debug("トピック再オープン対象外: id=%s（未検出 or 既にopen）", topic_id)
    return result


async def updateTopic(
    conn: AsyncConnection,
    topic_id: int,
    name: str | None = None,
    emotion: dict[str, int] | None = None,
    important: bool | None = None,
    add_message_ids: list[int] | None = None,
    remove_message_ids: list[int] | None = None,
) -> dict | None:
    """トピックを部分更新する。

    指定されたフィールドのみ更新し、未指定フィールドは既存値を保持する。
    add_message_ids指定時はメッセージ紐付け追加、remove_message_ids指定時は紐付け削除。

    Args:
        conn: DB接続
        topic_id: トピックID
        name: トピック名
        emotion: 感情値 {"joy": int, "anger": int, "sorrow": int, "fun": int}
        important: 重要フラグ
        add_message_ids: 紐付け追加するメッセージIDリスト
        remove_message_ids: 紐付け削除するメッセージIDリスト

    Returns:
        更新後のトピックdict（message_count含む）、未検出の場合はNone
    """
    # 感情値のキー・値域チェック
    validateEmotion(emotion)

    # SET句の動的構築
    set_clauses: list[str] = []
    params: list = []

    if name is not None:
        set_clauses.append("name = %s")
        params.append(name)

    if emotion is not None:
        for key in ("joy", "anger", "sorrow", "fun"):
            if key in emotion:
                set_clauses.append(f"{key} = %s")
                params.append(emotion[key])

    if important is not None:
        set_clauses.append("important = %s")
        params.append(important)

    if set_clauses:
        set_clause = ", ".join(set_clauses)
        params.append(topic_id)
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                UPDATE t_topics
                SET {set_clause}
                WHERE id = %s
                RETURNING *
                """,
                params,
            )
            topic = await cur.fetchone()
    else:
        # SET句がない場合はSELECTのみ（メッセージ紐付け変更だけの可能性）
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM t_topics WHERE id = %s",
                (topic_id,),
            )
            topic = await cur.fetchone()

    if not topic:
        logger.debug("トピック未検出: id=%s", topic_id)
        return None

    # メッセージ紐付け追加
    if add_message_ids:
        await linkMessageTopics(conn, add_message_ids, topic_id)

    # メッセージ紐付け削除
    if remove_message_ids:
        await unlinkMessageTopics(conn, remove_message_ids, topic_id)

    # message_count取得
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT COUNT(*) FROM t_message_topics WHERE topic_id = %s",
            (topic_id,),
        )
        message_count = (await cur.fetchone())["count"]

    result = dict(topic)
    result["message_count"] = message_count
    logger.debug("トピック更新: id=%s", topic_id)
    return result


async def getTopicById(
    conn: AsyncConnection,
    topic_id: int,
) -> dict | None:
    """トピック情報を取得する。

    Args:
        conn: DB接続
        topic_id: トピックID

    Returns:
        トピックのdict（message_count含む）、未検出の場合はNone
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT t.*, COUNT(mt.message_id) AS message_count
            FROM t_topics t
            LEFT JOIN t_message_topics mt ON t.id = mt.topic_id
            WHERE t.id = %s
            GROUP BY t.id
            """,
            (topic_id,),
        )
        topic = await cur.fetchone()

    if not topic:
        logger.debug("トピック未検出: id=%s", topic_id)
        return None

    return dict(topic)
