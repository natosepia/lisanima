"""ロールリポジトリ

m_role テーブルおよび t_message_roles テーブルへの操作を提供する。
"""
import logging

from psycopg import AsyncConnection

logger = logging.getLogger(__name__)


async def findOrCreateRoles(
    conn: AsyncConnection,
    role_names: list[str],
) -> list[dict]:
    """ロール名のリストから、既存ロールを検索し未登録ロールは作成する。

    正規化: strip() + lower()（ロール名は英語のみのためNFKCは不要）

    Args:
        conn: DB接続
        role_names: ロール名リスト（正規化前）

    Returns:
        ロールのdictリスト（id, name）
    """
    if not role_names:
        return []

    # 正規化 + 重複除去（順序維持）
    normalized = list(dict.fromkeys(
        n.strip().lower() for n in role_names if n.strip()
    ))

    roles = []
    async with conn.cursor() as cur:
        for name in normalized:
            # INSERT ... ON CONFLICT で upsert
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


async def linkMessageRoles(
    conn: AsyncConnection,
    message_id: int,
    role_ids: list[int],
) -> None:
    """メッセージとロールを紐付ける。

    Args:
        conn: DB接続
        message_id: メッセージID
        role_ids: ロールIDリスト
    """
    if not role_ids:
        return

    async with conn.cursor() as cur:
        for role_id in role_ids:
            await cur.execute(
                """
                INSERT INTO t_message_roles (message_id, role_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (message_id, role_id),
            )


async def linkMessageRolesBatch(
    conn: AsyncConnection,
    message_ids: list[int],
    role_ids: list[int],
) -> int:
    """複数メッセージに対してロールを一括紐付けする。

    Args:
        conn: DB接続
        message_ids: メッセージIDリスト
        role_ids: ロールIDリスト

    Returns:
        挿入行数
    """
    if not message_ids or not role_ids:
        return 0

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO t_message_roles (message_id, role_id)
            SELECT m_id, r_id
            FROM unnest(%s::int[]) AS m_id
            CROSS JOIN unnest(%s::int[]) AS r_id
            ON CONFLICT DO NOTHING
            """,
            (message_ids, role_ids),
        )
        inserted = cur.rowcount
        logger.debug(
            "ロール一括紐付け: messages=%d, roles=%d, inserted=%d",
            len(message_ids), len(role_ids), inserted,
        )
        return inserted
