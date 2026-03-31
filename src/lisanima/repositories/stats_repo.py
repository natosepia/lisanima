"""統計リポジトリ

recall mode="stats" 用の統計クエリを提供する。
メッセージ・タグ・トピック・ロールの利用状況を集計する。
"""
import logging
from datetime import datetime

from psycopg import AsyncConnection

logger = logging.getLogger(__name__)


async def getMessageStats(
    conn: AsyncConnection,
    since: datetime | None = None,
) -> dict:
    """メッセージのサマリー統計を取得する。

    Args:
        conn: DB接続
        since: 期間指定（この日時以降のメッセージを対象）

    Returns:
        {"total_messages": int, "active_messages": int, "deleted_messages": int}
    """
    conditions: list[str] = []
    params: list = []

    if since:
        conditions.append("created_at >= %s")
        params.append(since)

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT
                COUNT(*) AS total_messages,
                COUNT(*) FILTER (WHERE is_deleted = FALSE) AS active_messages,
                COUNT(*) FILTER (WHERE is_deleted = TRUE) AS deleted_messages
            FROM t_messages
            WHERE {where_clause}
            """,
            params,
        )
        row = await cur.fetchone()

    logger.debug("メッセージ統計: %s", dict(row))
    return dict(row)


async def getTagStats(
    conn: AsyncConnection,
    since: datetime | None = None,
) -> dict:
    """タグの利用統計を取得する。

    タグ一覧と利用件数を集計する。論理削除済みメッセージは除外。

    Args:
        conn: DB接続
        since: 期間指定（この日時以降のメッセージを対象）

    Returns:
        {"total": int, "usage": [{"name": str, "count": int}], "unused": [str]}
    """
    # since条件: メッセージのcreated_atでフィルタ
    since_condition = ""
    params: list = []
    if since:
        since_condition = "AND m.created_at >= %s"
        params.append(since)

    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT
                tg.name,
                COUNT(m.id) AS count
            FROM t_tags tg
            LEFT JOIN t_message_tags mt ON tg.id = mt.tag_id
            LEFT JOIN t_messages m ON mt.message_id = m.id
                AND m.is_deleted = FALSE
                {since_condition}
            GROUP BY tg.id, tg.name
            ORDER BY count DESC, tg.name
            """,
            params,
        )
        rows = await cur.fetchall()

    usage = []
    unused = []
    for row in rows:
        if row["count"] > 0:
            usage.append({"name": row["name"], "count": row["count"]})
        else:
            unused.append(row["name"])

    result = {
        "total": len(rows),
        "usage": usage,
        "unused": unused,
    }
    logger.debug("タグ統計: total=%d, used=%d, unused=%d", len(rows), len(usage), len(unused))
    return result


async def getTopicStats(
    conn: AsyncConnection,
    since: datetime | None = None,
) -> dict:
    """トピックの利用統計を取得する。

    トピック一覧とステータス別集計・メッセージ数を返す。
    論理削除済みメッセージは除外。

    Args:
        conn: DB接続
        since: 期間指定（この日時以降のメッセージを対象）

    Returns:
        {"total": int, "by_status": {"open": int, "closed": int},
         "list": [{"id": int, "name": str, "status": str, "message_count": int}]}
    """
    since_condition = ""
    params: list = []
    if since:
        since_condition = "AND m.created_at >= %s"
        params.append(since)

    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT
                tp.id,
                tp.name,
                tp.status,
                COUNT(m.id) AS message_count
            FROM t_topics tp
            LEFT JOIN t_message_topics mt ON tp.id = mt.topic_id
            LEFT JOIN t_messages m ON mt.message_id = m.id
                AND m.is_deleted = FALSE
                {since_condition}
            GROUP BY tp.id, tp.name, tp.status
            ORDER BY message_count DESC, tp.name
            """,
            params,
        )
        rows = await cur.fetchall()

    topic_list = []
    by_status: dict[str, int] = {"open": 0, "closed": 0}
    for row in rows:
        topic_list.append({
            "id": row["id"],
            "name": row["name"],
            "status": row["status"],
            "message_count": row["message_count"],
        })
        status = row["status"]
        if status in by_status:
            by_status[status] += 1

    result = {
        "total": len(rows),
        "by_status": by_status,
        "list": topic_list,
    }
    logger.debug("トピック統計: total=%d, open=%d, closed=%d",
                 len(rows), by_status["open"], by_status["closed"])
    return result


async def getRoleStats(
    conn: AsyncConnection,
    since: datetime | None = None,
) -> dict:
    """ロールの利用統計を取得する。

    ロール一覧と利用件数を集計する。論理削除済みメッセージは除外。

    Args:
        conn: DB接続
        since: 期間指定（この日時以降のメッセージを対象）

    Returns:
        {"usage": [{"name": str, "count": int}]}
    """
    since_condition = ""
    params: list = []
    if since:
        since_condition = "AND m.created_at >= %s"
        params.append(since)

    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT
                r.name,
                COUNT(m.id) AS count
            FROM m_role r
            LEFT JOIN t_message_roles mr ON r.id = mr.role_id
            LEFT JOIN t_messages m ON mr.message_id = m.id
                AND m.is_deleted = FALSE
                {since_condition}
            GROUP BY r.id, r.name
            ORDER BY count DESC, r.name
            """,
            params,
        )
        rows = await cur.fetchall()

    usage = [{"name": row["name"], "count": row["count"]} for row in rows]

    logger.debug("ロール統計: total=%d", len(usage))
    return {"usage": usage}
