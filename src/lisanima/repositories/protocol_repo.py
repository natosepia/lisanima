"""プロトコルリポジトリ

m_rulebook_protocol_detail テーブルへの操作を提供する。
rulebook が「何をすべきか（what）」、protocol_detail は「どうやるか（how）」。
"""
import logging

from psycopg import AsyncConnection

logger = logging.getLogger(__name__)


async def getProtocol(
    conn: AsyncConnection,
    protocol_name: str,
) -> list[dict]:
    """指定 protocol_name の全ステップを seq 順で取得する。

    Args:
        conn: DB接続
        protocol_name: 手順名（例: 'compact', 'reflect'）

    Returns:
        ステップのdictリスト（seq昇順）。該当なしは空リスト。
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT seq, content, exportable, created_at, updated_at
            FROM m_rulebook_protocol_detail
            WHERE protocol_name = %s
            ORDER BY seq
            """,
            (protocol_name,),
        )
        rows = await cur.fetchall()

    logger.debug(
        "プロトコル取得: protocol_name=%s, count=%d",
        protocol_name, len(rows),
    )
    return rows


async def setProtocol(
    conn: AsyncConnection,
    protocol_name: str,
    seq: int,
    content: str,
    exportable: bool = False,
) -> dict:
    """ステップを追加または更新する（UPSERT）。

    既存(protocol_name, seq)が存在すればcontent/exportable/updated_atを更新、
    なければ新規INSERTする。

    Args:
        conn: DB接続
        protocol_name: 手順名
        seq: ステップ番号
        content: ステップ内容（Markdown可）
        exportable: .claude/rules/ エクスポート対象フラグ

    Returns:
        UPSERT後の行のdict
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO m_rulebook_protocol_detail
                (protocol_name, seq, content, exportable)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (protocol_name, seq) DO UPDATE
                SET content = EXCLUDED.content,
                    exportable = EXCLUDED.exportable,
                    updated_at = NOW()
            RETURNING protocol_name, seq, content, exportable, created_at, updated_at
            """,
            (protocol_name, seq, content, exportable),
        )
        row = await cur.fetchone()

    logger.debug(
        "プロトコル保存: protocol_name=%s, seq=%d",
        protocol_name, seq,
    )
    return row


async def listProtocols(conn: AsyncConnection) -> list[dict]:
    """登録済みプロトコル名一覧をステップ数つきで取得する。

    Args:
        conn: DB接続

    Returns:
        [{protocol_name, step_count}] のリスト（protocol_name昇順）
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT protocol_name, COUNT(*)::int AS step_count
            FROM m_rulebook_protocol_detail
            GROUP BY protocol_name
            ORDER BY protocol_name
            """
        )
        rows = await cur.fetchall()

    logger.debug("プロトコル一覧取得: count=%d", len(rows))
    return rows
