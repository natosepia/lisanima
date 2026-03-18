"""タグリポジトリ

t_tags テーブルおよび t_message_tags テーブルへの操作を提供する。
"""
import logging
import unicodedata

from psycopg import AsyncConnection

logger = logging.getLogger(__name__)


def normalizeTagName(name: str) -> str:
    """タグ名を正規化する。

    - 前後空白を除去
    - 小文字化
    - 全角英数字を半角に変換（NFKC正規化）

    Args:
        name: 生のタグ名

    Returns:
        正規化されたタグ名
    """
    return unicodedata.normalize("NFKC", name.strip()).lower()


async def findOrCreateTags(
    conn: AsyncConnection,
    tag_names: list[str],
) -> list[dict]:
    """タグ名のリストから、既存タグを検索し未登録タグは作成する。

    Args:
        conn: DB接続
        tag_names: タグ名リスト（正規化前）

    Returns:
        タグのdictリスト（id, name）
    """
    if not tag_names:
        return []

    normalized = [normalizeTagName(n) for n in tag_names if n.strip()]
    normalized = list(dict.fromkeys(normalized))  # 重複除去（順序維持）

    tags = []
    async with conn.cursor() as cur:
        for name in normalized:
            # INSERT ... ON CONFLICT でupsert
            await cur.execute(
                """
                INSERT INTO t_tags (name) VALUES (%s)
                ON CONFLICT (name) DO NOTHING
                RETURNING id, name
                """,
                (name,),
            )
            row = await cur.fetchone()
            if row:
                tags.append(row)
            else:
                # 既に存在する場合はSELECT
                await cur.execute(
                    "SELECT id, name FROM t_tags WHERE name = %s",
                    (name,),
                )
                tags.append(await cur.fetchone())

    logger.debug("タグ取得/作成: %s", [t["name"] for t in tags])
    return tags


async def linkMessageTags(
    conn: AsyncConnection,
    message_id: int,
    tag_ids: list[int],
) -> None:
    """メッセージとタグを紐付ける。

    Args:
        conn: DB接続
        message_id: メッセージID
        tag_ids: タグIDリスト
    """
    if not tag_ids:
        return

    async with conn.cursor() as cur:
        for tag_id in tag_ids:
            await cur.execute(
                """
                INSERT INTO t_message_tags (message_id, tag_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (message_id, tag_id),
            )


async def unlinkMessageTags(
    conn: AsyncConnection,
    message_id: int,
    tag_ids: list[int],
) -> int:
    """メッセージからタグの紐付けを削除する。

    Args:
        conn: DB接続
        message_id: メッセージID
        tag_ids: 削除するタグIDリスト

    Returns:
        削除行数
    """
    if not tag_ids:
        return 0

    async with conn.cursor() as cur:
        await cur.execute(
            """
            DELETE FROM t_message_tags
            WHERE message_id = %s AND tag_id = ANY(%s)
            """,
            (message_id, tag_ids),
        )
        deleted = cur.rowcount
        logger.debug("タグ紐付け削除: message_id=%s, count=%d", message_id, deleted)
        return deleted


async def linkMessageTagsBatch(
    conn: AsyncConnection,
    message_ids: list[int],
    tag_ids: list[int],
) -> int:
    """複数メッセージに対してタグを一括紐付けする。

    Args:
        conn: DB接続
        message_ids: メッセージIDリスト
        tag_ids: タグIDリスト

    Returns:
        挿入行数
    """
    if not message_ids or not tag_ids:
        return 0

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO t_message_tags (message_id, tag_id)
            SELECT m_id, t_id
            FROM unnest(%s::int[]) AS m_id
            CROSS JOIN unnest(%s::int[]) AS t_id
            ON CONFLICT DO NOTHING
            """,
            (message_ids, tag_ids),
        )
        inserted = cur.rowcount
        logger.debug(
            "タグ一括紐付け: messages=%d, tags=%d, inserted=%d",
            len(message_ids), len(tag_ids), inserted,
        )
        return inserted


async def unlinkMessageTagsBatch(
    conn: AsyncConnection,
    message_ids: list[int],
    tag_names: list[str],
) -> int:
    """複数メッセージから指定タグ名の紐付けを一括削除する。

    Args:
        conn: DB接続
        message_ids: メッセージIDリスト
        tag_names: 削除するタグ名リスト

    Returns:
        削除行数
    """
    if not message_ids or not tag_names:
        return 0

    normalized = [normalizeTagName(n) for n in tag_names if n.strip()]
    if not normalized:
        return 0

    async with conn.cursor() as cur:
        await cur.execute(
            """
            DELETE FROM t_message_tags
            WHERE message_id = ANY(%s)
              AND tag_id IN (SELECT id FROM t_tags WHERE name = ANY(%s))
            """,
            (message_ids, normalized),
        )
        deleted = cur.rowcount
        logger.debug(
            "タグ一括紐付け削除: messages=%d, tags=%s, deleted=%d",
            len(message_ids), normalized, deleted,
        )
        return deleted
