"""メッセージリポジトリ

t_messages テーブルへのCRUD操作を提供する。
"""
import logging

from psycopg import AsyncConnection, sql

from lisanima.repositories._validators import VALID_EMOTION_AXES

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
    # 感情値の値域チェック（0-255の整数）
    for axis_name, axis_val in [("joy", joy), ("anger", anger), ("sorrow", sorrow), ("fun", fun)]:
        if not isinstance(axis_val, int) or not (0 <= axis_val <= 255):
            raise ValueError(f"{axis_name} は 0〜255 の整数で指定してください: {axis_val}")

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
    query: list[str] | None = None,
    tags: list[str] | None = None,
    speaker: str | None = None,
    project: str | None = None,
    topic_id: list[int] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    emotion_filter: dict | None = None,
    limit: int = 20,
    offset: int = 0,
    include_deleted: bool = False,
) -> dict:
    """t_messages テーブルからメッセージを検索する。

    Args:
        conn: DB接続
        query: 全文検索キーワード（AND検索）
        tags: タグ名フィルタ（AND検索）
        speaker: 発言者フィルタ
        project: プロジェクト名フィルタ
        topic_id: トピックIDフィルタ（OR検索）
        date_from: 日付範囲開始（YYYY-MM-DD）
        date_to: 日付範囲終了（YYYY-MM-DD）
        emotion_filter: 感情値レンジフィルタ
        limit: 取得件数上限
        offset: オフセット
        include_deleted: 論理削除済みも含める（デフォルト: False）

    Returns:
        {"total": int, "messages": list[dict]}
    """
    # パラメータの型を保証（MCP経由で非int値が渡される場合の防御）
    limit = int(limit)
    offset = int(offset)

    # limit / offset の値域チェック
    if limit < 1:
        raise ValueError("limit は 1 以上で指定してください")
    if offset < 0:
        raise ValueError("offset は 0 以上で指定してください")

    # WHERE句の動的構築
    conditions: list[str] = []
    if not include_deleted:
        conditions.append("m.is_deleted = FALSE")
    params: list = []

    # query: 複数キーワードAND検索（各キーワードで部分一致）
    # pg_trgm の % 演算子は日本語短文で similarity が極端に低くなるため LIKE に変更。
    # ORDER BY で similarity() を使い関連度ソートは維持する。
    if query:
        for keyword in query:
            # LIKE特殊文字（%, _, \）をエスケープしてからワイルドカードで囲む
            escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append("m.content LIKE %s ESCAPE '\\'")
            params.append(f"%{escaped}%")

    if speaker:
        conditions.append("m.speaker = %s")
        params.append(speaker)

    if project:
        conditions.append("s.project = %s")
        params.append(project)

    # topic_id: OR検索（いずれかのトピックに紐づくセッション）
    if topic_id:
        conditions.append(
            "m.session_id IN (SELECT session_id FROM t_session_topics WHERE topic_id = ANY(%s))"
        )
        params.append(topic_id)

    # emotion_filter: 各軸ごとに min/max でレンジ条件
    if emotion_filter:
        for axis, range_spec in emotion_filter.items():
            # 感情軸名をホワイトリスト検証（SQL識別子として使用するため）
            if axis not in VALID_EMOTION_AXES:
                raise ValueError(f"不正な感情軸: '{axis}'")
            if not range_spec:
                continue
            if "min" in range_spec:
                conditions.append(f"m.{axis} >= %s")
                params.append(range_spec["min"])
            if "max" in range_spec:
                conditions.append(f"m.{axis} <= %s")
                params.append(range_spec["max"])

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

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    # タグのAND検索: HAVING COUNT で全タグ一致を保証
    group_by = ""
    having = ""
    having_params: list = []
    if tags:
        group_by = "GROUP BY m.id, s.id"
        having = "HAVING COUNT(DISTINCT t.name) = %s"
        having_params = [len(tags)]

    # ORDER BY: query指定時はpg_trgm類似度（先頭キーワードで代表）、それ以外は新しい順
    if query:
        order_by = "ORDER BY similarity(m.content, %s) DESC, m.emotion_total DESC, m.created_at DESC"
        order_params = [query[0]]
    else:
        order_by = "ORDER BY m.created_at DESC"
        order_params = []

    async with conn.cursor() as cur:
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

        # offsetがtotal以上なら空結果を早期リターン（不要なクエリを回避）
        if offset >= total and total > 0:
            return {"total": total, "messages": []}

        # データ取得
        data_sql = f"""
            SELECT m.id, s.date AS session_date, m.speaker, m.target,
                   m.content, m.joy, m.anger, m.sorrow, m.fun,
                   m.emotion_total, m.source, s.project,
                   m.created_at
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


async def softDelete(
    conn: AsyncConnection,
    message_id: int,
    reason: str = "none",
) -> dict | None:
    """メッセージを論理削除する。

    Args:
        conn: DB接続
        message_id: 削除対象のメッセージID
        reason: 削除理由

    Returns:
        更新されたレコード。存在しない/既に削除済みの場合はNone
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE t_messages
            SET is_deleted = TRUE, deleted_reason = %s
            WHERE id = %s AND is_deleted = FALSE
            RETURNING id
            """,
            (reason, message_id),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        logger.debug("メッセージ論理削除: id=%s, reason=%s", message_id, reason)
        return dict(row)


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
