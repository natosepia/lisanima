"""統計リポジトリ

recall mode="stats" / mode="hot" 用の統計・スコアリングクエリを提供する。
メッセージ・タグ・トピック・ロールの利用状況を集計する。
"""
import logging
from datetime import datetime

from psycopg import AsyncConnection

from lisanima.repositories.message_repo import (
    _getMessageRolesBatch,
    _getMessageTagsBatch,
)

logger = logging.getLogger(__name__)


def _buildExcludeTagsCondition(
    table_alias: str,
    exclude_tags: list[str] | None,
    params: list,
) -> str:
    """exclude_tags用のNOT EXISTSサブクエリを構築する。

    指定タグを持つメッセージを集計対象から除外するSQL条件を返す。

    Args:
        table_alias: メッセージテーブルのエイリアス（例: "m"）
        exclude_tags: 除外するタグ名リスト
        params: SQLパラメータリスト（IN句の値が追加される）

    Returns:
        SQL条件文字列。exclude_tagsが空またはNoneの場合は空文字列
    """
    if not exclude_tags:
        return ""

    # IN句用のプレースホルダを生成
    placeholders = ", ".join(["%s"] * len(exclude_tags))
    params.extend(exclude_tags)

    return f"""AND NOT EXISTS (
                SELECT 1 FROM t_message_tags ext
                JOIN t_tags ext_t ON ext.tag_id = ext_t.id
                WHERE ext.message_id = {table_alias}.id
                AND ext_t.name IN ({placeholders})
            )"""


async def getMessageStats(
    conn: AsyncConnection,
    since: datetime | None = None,
    exclude_tags: list[str] | None = None,
) -> dict:
    """メッセージのサマリー統計を取得する。

    Args:
        conn: DB接続
        since: 期間指定（この日時以降のメッセージを対象）
        exclude_tags: 除外するタグ名リスト（該当タグを持つメッセージを集計から除外）

    Returns:
        {"total_messages": int, "active_messages": int, "deleted_messages": int}
    """
    conditions: list[str] = []
    params: list = []

    if since:
        conditions.append("created_at >= %s")
        params.append(since)

    # exclude_tags条件を追加
    exclude_condition = _buildExcludeTagsCondition("t_messages", exclude_tags, params)
    if exclude_condition:
        conditions.append(exclude_condition.removeprefix("AND "))

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
    min_occurrences: int | None = None,
    exclude_tags: list[str] | None = None,
) -> dict:
    """タグの利用統計を取得する。

    タグ一覧と利用件数を集計する。論理削除済みメッセージは除外。

    Args:
        conn: DB接続
        since: 期間指定（この日時以降のメッセージを対象）
        min_occurrences: 最低出現回数（指定時はcount >= min_occurrences の行のみ返す）
        exclude_tags: 除外するタグ名リスト（該当タグを持つメッセージを集計から除外）

    Returns:
        {"total": int, "usage": [{"name": str, "count": int}], "unused": [str]}
    """
    # since条件: メッセージのcreated_atでフィルタ
    since_condition = ""
    params: list = []
    if since:
        since_condition = "AND m.created_at >= %s"
        params.append(since)

    # exclude_tags条件: 指定タグを持つメッセージを集計から除外
    exclude_condition = _buildExcludeTagsCondition("m", exclude_tags, params)

    # min_occurrences条件: HAVING句でフィルタ
    having_clause = ""
    if min_occurrences is not None:
        having_clause = "HAVING COUNT(m.id) >= %s"
        params.append(min_occurrences)

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
                {exclude_condition}
            GROUP BY tg.id, tg.name
            {having_clause}
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
    min_occurrences: int | None = None,
    exclude_tags: list[str] | None = None,
) -> dict:
    """トピックの利用統計を取得する。

    トピック一覧とステータス別集計・メッセージ数を返す。
    論理削除済みメッセージは除外。

    Args:
        conn: DB接続
        since: 期間指定（この日時以降のメッセージを対象）
        min_occurrences: 最低メッセージ数（指定時はmessage_count >= min_occurrences の行のみ返す）
        exclude_tags: 除外するタグ名リスト（該当タグを持つメッセージを集計から除外）

    Returns:
        {"total": int, "by_status": {"open": int, "closed": int},
         "list": [{"id": int, "name": str, "status": str, "message_count": int}]}
    """
    since_condition = ""
    params: list = []
    if since:
        since_condition = "AND m.created_at >= %s"
        params.append(since)

    # exclude_tags条件: 指定タグを持つメッセージを集計から除外
    exclude_condition = _buildExcludeTagsCondition("m", exclude_tags, params)

    # min_occurrences条件: HAVING句でフィルタ
    having_clause = ""
    if min_occurrences is not None:
        having_clause = "HAVING COUNT(m.id) >= %s"
        params.append(min_occurrences)

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
                {exclude_condition}
            GROUP BY tp.id, tp.name, tp.status
            {having_clause}
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
    min_occurrences: int | None = None,
    exclude_tags: list[str] | None = None,
) -> dict:
    """ロールの利用統計を取得する。

    ロール一覧と利用件数を集計する。論理削除済みメッセージは除外。

    Args:
        conn: DB接続
        since: 期間指定（この日時以降のメッセージを対象）
        min_occurrences: 最低出現回数（指定時はcount >= min_occurrences の行のみ返す）
        exclude_tags: 除外するタグ名リスト（該当タグを持つメッセージを集計から除外）

    Returns:
        {"usage": [{"name": str, "count": int}]}
    """
    since_condition = ""
    params: list = []
    if since:
        since_condition = "AND m.created_at >= %s"
        params.append(since)

    # exclude_tags条件: 指定タグを持つメッセージを集計から除外
    exclude_condition = _buildExcludeTagsCondition("m", exclude_tags, params)

    # min_occurrences条件: HAVING句でフィルタ
    having_clause = ""
    if min_occurrences is not None:
        having_clause = "HAVING COUNT(m.id) >= %s"
        params.append(min_occurrences)

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
                {exclude_condition}
            GROUP BY r.id, r.name
            {having_clause}
            ORDER BY count DESC, r.name
            """,
            params,
        )
        rows = await cur.fetchall()

    usage = [{"name": row["name"], "count": row["count"]} for row in rows]

    logger.debug("ロール統計: total=%d", len(usage))
    return {"usage": usage}


async def getHotMessages(
    conn: AsyncConnection,
    limit: int = 10,
) -> dict:
    """感情×トピック×鮮度の複合スコアで上位メッセージを取得する。

    スコアリング:
        score = 0.50 * emotion_score
              + 0.25 * topic_score
              + 0.25 * recency_score

    - emotion_score: emotion_total / 1024.0 (0.0〜1.0)
    - topic_score: openトピックに紐付き → 1.0、それ以外 → 0.0
    - recency_score: EXP(-経過秒 / (30日*86400)) (30日で約37%に減衰)

    Args:
        conn: DB接続
        limit: 取得件数上限（デフォルト: 10）

    Returns:
        {"total": int, "messages": [dict]}
        各メッセージにhot_score, tags, rolesを含む
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                m.id,
                m.session_id,
                m.speaker,
                m.target,
                m.content,
                m.joy, m.anger, m.sorrow, m.fun,
                m.emotion_total,
                m.source,
                m.created_at,
                (
                    0.50 * (m.emotion_total / 1024.0)
                  + 0.25 * CASE WHEN EXISTS (
                        SELECT 1 FROM t_message_topics mt2
                        JOIN t_topics tp ON mt2.topic_id = tp.id
                        WHERE mt2.message_id = m.id AND tp.status = 'open'
                    ) THEN 1.0 ELSE 0.0 END
                  + 0.25 * EXP(-EXTRACT(EPOCH FROM (NOW() - m.created_at)) / (30.0 * 86400))
                ) AS hot_score
            FROM t_messages m
            WHERE m.is_deleted = FALSE
            ORDER BY hot_score DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = await cur.fetchall()

    # タグ・ロールの一括取得（N+1防止）
    message_ids = [row["id"] for row in rows]
    tags_by_msg: dict[int, list[str]] = {}
    roles_by_msg: dict[int, list[str]] = {}

    if message_ids:
        tags_by_msg = await _getMessageTagsBatch(conn, message_ids)
        roles_by_msg = await _getMessageRolesBatch(conn, message_ids)

    # レスポンス構築
    messages = []
    for row in rows:
        msg = dict(row)
        msg["emotion"] = {
            "joy": msg.pop("joy"),
            "anger": msg.pop("anger"),
            "sorrow": msg.pop("sorrow"),
            "fun": msg.pop("fun"),
        }
        msg["hot_score"] = round(msg["hot_score"], 3)
        msg["tags"] = tags_by_msg.get(msg["id"], [])
        msg["roles"] = roles_by_msg.get(msg["id"], [])
        messages.append(msg)

    total = len(messages)
    logger.debug("hotメッセージ取得: total=%d", total)
    return {"total": total, "messages": messages}
