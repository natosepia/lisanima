"""メッセージリポジトリ

t_messages テーブルへのCRUD操作を提供する。
"""
import logging

from psycopg import AsyncConnection, sql

logger = logging.getLogger(__name__)


async def insertMessage(
    conn: AsyncConnection,
    session_id: int,
    speaker: str,
    content: str,
    joy: int = 0,
    anger: int = 0,
    sorrow: int = 0,
    fun: int = 0,
    target: str | None = None,
    source: str = "unknown",
) -> dict:
    """メッセージを保存する。

    Args:
        conn: DB接続
        session_id: セッションID
        speaker: 発言者
        content: 発言内容
        joy: 喜び (0-255)
        anger: 怒り (0-255)
        sorrow: 哀しみ (0-255)
        fun: 楽しさ (0-255)
        target: 発言先（Noneの場合は'*'をデフォルト）
        source: MCPクライアント識別子

    Returns:
        保存したメッセージのdict
    """
    # targetがNoneの場合はDBデフォルトに合わせて'*'を設定
    if target is None:
        target = "*"

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO t_messages (session_id, speaker, content, joy, anger, sorrow, fun, target, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, session_id, speaker, target, content,
                      joy, anger, sorrow, fun, emotion_total, source, is_deleted, created_at
            """,
            (session_id, speaker, content, joy, anger, sorrow, fun, target, source),
        )
        msg = await cur.fetchone()
        logger.debug("メッセージ保存: id=%s, session_id=%s", msg["id"], session_id)
        return msg


async def searchMessages(
    conn: AsyncConnection,
    query: str | None = None,
    tags: list[str] | None = None,
    speaker: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_emotion: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """t_messages テーブルからメッセージを検索する。

    Args:
        conn: DB接続
        query: 全文検索キーワード
        tags: タグ名フィルタ（AND検索）
        speaker: 発言者フィルタ
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
        # pg_trgm の % 演算子でGINインデックスを活用
        conditions.append("m.content %% %s")
        params.append(query)

    if speaker:
        conditions.append("m.speaker = %s")
        params.append(speaker)

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
            JOIN t_message_tags mt ON m.id = mt.message_id
            JOIN t_tags t ON mt.tag_id = t.id
        """
        placeholders = ", ".join(["%s"] * len(tags))
        conditions.append(f"t.name IN ({placeholders})")
        params.extend([t.lower().strip() for t in tags])

    where_clause = " AND ".join(conditions)

    # タグのAND検索: HAVING COUNT で全タグ一致を保証
    group_by = ""
    having = ""
    having_params: list = []
    if tags:
        group_by = "GROUP BY m.id, s.date"
        having = "HAVING COUNT(DISTINCT t.name) = %s"
        having_params = [len(tags)]

    # ORDER BY: query指定時はpg_trgm類似度、それ以外は新しい順
    if query:
        order_by = "ORDER BY similarity(m.content, %s) DESC, m.emotion_total DESC, m.created_at DESC"
        order_params = [query]
    else:
        order_by = "ORDER BY m.created_at DESC"
        order_params = []

    async with conn.cursor() as cur:
        # 日本語の短いクエリ向けにsimilarity閾値を下げる
        if query:
            await cur.execute("SET pg_trgm.similarity_threshold = 0.1")

        # 件数取得
        count_sql = f"""
            SELECT COUNT(*) FROM (
                SELECT m.id
                FROM t_messages m
                JOIN t_sessions s ON m.session_id = s.id
                {tag_join}
                WHERE {where_clause}
                {group_by}
                {having}
            ) sub
        """
        await cur.execute(count_sql, params + having_params)
        total = (await cur.fetchone())["count"]

        # データ取得
        data_sql = f"""
            SELECT m.id, s.date AS session_date, m.speaker, m.target,
                   m.content, m.joy, m.anger, m.sorrow, m.fun,
                   m.emotion_total, m.created_at
            FROM t_messages m
            JOIN t_sessions s ON m.session_id = s.id
            {tag_join}
            WHERE {where_clause}
            {group_by}
            {having}
            {order_by}
            LIMIT %s OFFSET %s
        """
        await cur.execute(
            data_sql,
            params + having_params + order_params + [limit, offset],
        )
        rows = await cur.fetchall()

    # メッセージIDリストをまとめてタグを一括取得（N+1防止）
    messages = []
    message_ids = [row["id"] for row in rows]
    tags_by_msg: dict[int, list[str]] = {}

    if message_ids:
        tags_by_msg = await _getMessageTagsBatch(conn, message_ids)

    # 感情値を辞書にまとめて返す
    for row in rows:
        msg = dict(row)
        msg["emotion"] = {
            "joy": msg.pop("joy"),
            "anger": msg.pop("anger"),
            "sorrow": msg.pop("sorrow"),
            "fun": msg.pop("fun"),
        }
        msg["tags"] = tags_by_msg.get(msg["id"], [])
        messages.append(msg)

    logger.debug("メッセージ検索: total=%d, returned=%d", total, len(messages))
    return {"total": total, "messages": messages}


async def _getMessageTagsBatch(
    conn: AsyncConnection,
    message_ids: list[int],
) -> dict[int, list[str]]:
    """複数メッセージのタグを一括取得する。

    Args:
        conn: DB接続
        message_ids: メッセージIDリスト

    Returns:
        {message_id: [tag_name, ...]} の辞書
    """
    placeholders = ", ".join(["%s"] * len(message_ids))
    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT mt.message_id, t.name
            FROM t_message_tags mt
            JOIN t_tags t ON mt.tag_id = t.id
            WHERE mt.message_id IN ({placeholders})
            ORDER BY t.name
            """,
            message_ids,
        )
        rows = await cur.fetchall()

    tags_by_msg: dict[int, list[str]] = {}
    for row in rows:
        tags_by_msg.setdefault(row["message_id"], []).append(row["name"])
    return tags_by_msg
