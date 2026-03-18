"""トピックリポジトリ

t_topics / t_session_topics / t_topic_roles テーブルへのCRUD操作を提供する。
"""
import logging

from psycopg import AsyncConnection

logger = logging.getLogger(__name__)


async def _findOrCreateRoles(
    conn: AsyncConnection,
    role_names: list[str],
) -> list[dict]:
    """ロール名のリストから、既存ロールを検索し未登録ロールは作成する。

    tag_repo.findOrCreateTags と同等のパターン。

    Args:
        conn: DB接続
        role_names: ロール名リスト

    Returns:
        ロールのdictリスト（id, name）
    """
    if not role_names:
        return []

    # 重複除去（順序維持）
    normalized = list(dict.fromkeys(n.strip().lower() for n in role_names if n.strip()))

    roles = []
    async with conn.cursor() as cur:
        for name in normalized:
            await cur.execute(
                """
                INSERT INTO m_role (name) VALUES (%s)
                ON CONFLICT (name) DO NOTHING
                RETURNING id, name
                """,
                (name,),
            )
            row = await cur.fetchone()
            if row:
                roles.append(row)
            else:
                # 既に存在する場合はSELECT
                await cur.execute(
                    "SELECT id, name FROM m_role WHERE name = %s",
                    (name,),
                )
                roles.append(await cur.fetchone())

    logger.debug("ロール取得/作成: %s", [r["name"] for r in roles])
    return roles


async def _linkTopicRoles(
    conn: AsyncConnection,
    topic_id: int,
    role_ids: list[int],
) -> None:
    """トピックとロールを紐付ける。

    Args:
        conn: DB接続
        topic_id: トピックID
        role_ids: ロールIDリスト
    """
    if not role_ids:
        return

    async with conn.cursor() as cur:
        for role_id in role_ids:
            await cur.execute(
                """
                INSERT INTO t_topic_roles (topic_id, role_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (topic_id, role_id),
            )


async def _replaceTopicRoles(
    conn: AsyncConnection,
    topic_id: int,
    role_ids: list[int],
) -> None:
    """トピックのロール紐付けを洗い替えする（DELETE + INSERT）。

    Args:
        conn: DB接続
        topic_id: トピックID
        role_ids: 新しいロールIDリスト
    """
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM t_topic_roles WHERE topic_id = %s",
            (topic_id,),
        )
    await _linkTopicRoles(conn, topic_id, role_ids)


async def _getTopicRoles(
    conn: AsyncConnection,
    topic_id: int,
) -> list[str]:
    """トピックに紐付くロール名を取得する。

    Args:
        conn: DB接続
        topic_id: トピックID

    Returns:
        ロール名リスト
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT r.name
            FROM t_topic_roles tr
            JOIN m_role r ON tr.role_id = r.id
            WHERE tr.topic_id = %s
            ORDER BY r.name
            """,
            (topic_id,),
        )
        rows = await cur.fetchall()
    return [row["name"] for row in rows]


async def linkSessionTopic(
    conn: AsyncConnection,
    session_id: int,
    topic_id: int,
) -> None:
    """セッションとトピックを紐付ける（重複時は無視）。

    Args:
        conn: DB接続
        session_id: セッションID
        topic_id: トピックID
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO t_session_topics (session_id, topic_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (session_id, topic_id),
        )
    logger.debug("セッション-トピック紐付け: session_id=%s, topic_id=%s", session_id, topic_id)


async def createTopic(
    conn: AsyncConnection,
    name: str,
    emotion: dict[str, int] | None = None,
    roles: list[str] | None = None,
    session_id: int | None = None,
) -> dict:
    """トピックを作成する。

    Args:
        conn: DB接続
        name: トピック名
        emotion: 感情値 {"joy": int, "anger": int, "sorrow": int, "fun": int}
        roles: ロール名リスト（未登録のロールは自動作成）
        session_id: セッションID（指定時にt_session_topicsへも紐付け）

    Returns:
        作成したトピックのdict（roles含む）
    """
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

    # ロール紐付け
    role_names_list: list[str] = []
    if roles:
        role_records = await _findOrCreateRoles(conn, roles)
        await _linkTopicRoles(conn, topic_id, [r["id"] for r in role_records])
        role_names_list = [r["name"] for r in role_records]

    # セッション紐付け
    if session_id is not None:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO t_session_topics (session_id, topic_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (session_id, topic_id),
            )
        logger.debug("セッション紐付け: session_id=%s, topic_id=%s", session_id, topic_id)

    result = dict(topic)
    result["roles"] = role_names_list
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
    roles: list[str] | None = None,
) -> dict | None:
    """トピックを部分更新する。

    指定されたフィールドのみ更新し、未指定フィールドは既存値を保持する。
    roles指定時はt_topic_rolesを洗い替え（DELETE + INSERT）。

    Args:
        conn: DB接続
        topic_id: トピックID
        name: トピック名
        emotion: 感情値 {"joy": int, "anger": int, "sorrow": int, "fun": int}
        important: 重要フラグ
        roles: ロール名リスト（指定時は洗い替え）

    Returns:
        更新後のトピックdict（roles含む）、未検出の場合はNone
    """
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
        # SET句がない場合はSELECTのみ（roles更新だけの可能性）
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM t_topics WHERE id = %s",
                (topic_id,),
            )
            topic = await cur.fetchone()

    if not topic:
        logger.debug("トピック未検出: id=%s", topic_id)
        return None

    # ロール洗い替え
    if roles is not None:
        role_records = await _findOrCreateRoles(conn, roles)
        await _replaceTopicRoles(conn, topic_id, [r["id"] for r in role_records])
        role_names_list = [r["name"] for r in role_records]
    else:
        role_names_list = await _getTopicRoles(conn, topic_id)

    result = dict(topic)
    result["roles"] = role_names_list
    logger.debug("トピック更新: id=%s", topic_id)
    return result


async def getTopicById(
    conn: AsyncConnection,
    topic_id: int,
) -> dict | None:
    """トピック情報と紐付きロールを取得する。

    Args:
        conn: DB接続
        topic_id: トピックID

    Returns:
        トピックのdict（roles含む）、未検出の場合はNone
    """
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT * FROM t_topics WHERE id = %s",
            (topic_id,),
        )
        topic = await cur.fetchone()

    if not topic:
        logger.debug("トピック未検出: id=%s", topic_id)
        return None

    role_names = await _getTopicRoles(conn, topic_id)

    result = dict(topic)
    result["roles"] = role_names
    return result
