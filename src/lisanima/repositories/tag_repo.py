"""タグリポジトリ

tags テーブルおよび message_tags テーブルへの操作を提供する。
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
                INSERT INTO tags (name) VALUES (%s)
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
                    "SELECT id, name FROM tags WHERE name = %s",
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
                INSERT INTO message_tags (message_id, tag_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (message_id, tag_id),
            )
