"""セッションリポジトリ

sessions テーブルへのCRUD操作を提供する。
"""
from datetime import date

from psycopg import AsyncConnection


async def findOrCreateSession(
    conn: AsyncConnection,
    session_date: date,
    project: str | None = None,
    persona_id: str = "lisa",
) -> dict:
    """指定日付のセッションを取得、なければ作成する。

    同日に複数セッションがある場合、最新（session_seq最大）を返す。

    Args:
        conn: DB接続
        session_date: セッション日付
        project: プロジェクト名
        persona_id: 人格識別子

    Returns:
        セッションのdict（id, date, session_seq, ...）
    """
    async with conn.cursor() as cur:
        # 同日の最新セッションを検索
        await cur.execute(
            """
            SELECT * FROM sessions
            WHERE date = %s AND persona_id = %s
            ORDER BY session_seq DESC
            LIMIT 1
            """,
            (session_date, persona_id),
        )
        session = await cur.fetchone()

        if session:
            return session

        # 新規セッション作成
        await cur.execute(
            """
            INSERT INTO sessions (persona_id, date, session_seq, project)
            VALUES (%s, %s, 1, %s)
            RETURNING *
            """,
            (persona_id, session_date, project),
        )
        return await cur.fetchone()


async def endSession(
    conn: AsyncConnection,
    session_id: int,
) -> dict | None:
    """セッションを終了する（ended_atを現在時刻に設定）。

    Args:
        conn: DB接続
        session_id: セッションID

    Returns:
        更新後のセッションdict、見つからない場合はNone
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE sessions SET ended_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (session_id,),
        )
        return await cur.fetchone()
