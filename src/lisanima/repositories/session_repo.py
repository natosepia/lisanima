"""セッションリポジトリ

t_sessions テーブルへのCRUD操作を提供する。
"""
import logging
from datetime import date

from psycopg import AsyncConnection

logger = logging.getLogger(__name__)


async def findOrCreateSession(
    conn: AsyncConnection,
    session_date: date,
    project: str | None = None,
    persona_id: str = "lisa",
) -> dict:
    """指定日付のセッションを取得、なければ作成する。

    同日に複数セッションがある場合、最新（session_seq最大）を返す。
    FOR UPDATE によるロックで並行競合を防止する。

    Note:
        呼び出し元でトランザクションを開始していることを前提とする。
        FOR UPDATE ロックは外側トランザクション内で有効となる。

    Args:
        conn: DB接続（トランザクション開始済みであること）
        session_date: セッション日付
        project: プロジェクト名
        persona_id: 人格識別子

    Returns:
        セッションのdict（id, date, session_seq, ...）
    """
    async with conn.cursor() as cur:
        # FOR UPDATE でロックを取得し、並行INSERT時のrace conditionを防止
        await cur.execute(
            """
            SELECT * FROM t_sessions
            WHERE date = %s AND persona_id = %s
            ORDER BY session_seq DESC
            LIMIT 1
            FOR UPDATE
            """,
            (session_date, persona_id),
        )
        session = await cur.fetchone()

        if session:
            logger.debug(
                "既存セッション取得: id=%s, date=%s, seq=%s",
                session["id"], session_date, session["session_seq"],
            )
            return session

        # 新規セッション作成
        await cur.execute(
            """
            INSERT INTO t_sessions (persona_id, date, session_seq, project)
            VALUES (%s, %s, 1, %s)
            RETURNING *
            """,
            (persona_id, session_date, project),
        )
        new_session = await cur.fetchone()
        logger.debug(
            "新規セッション作成: id=%s, date=%s",
            new_session["id"], session_date,
        )
        return new_session


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
            UPDATE t_sessions SET ended_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (session_id,),
        )
        result = await cur.fetchone()
        if result:
            logger.debug("セッション終了: id=%s", session_id)
        else:
            logger.debug("セッション未検出: id=%s", session_id)
        return result
