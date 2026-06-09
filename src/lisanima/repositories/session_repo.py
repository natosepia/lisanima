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

    同日に複数セッションがある場合は最新（session_seq最大）を返す。

    並行制御:
        SELECT FOR UPDATE は対象行が「存在しない」場合にロックを取れず、
        並行INSERT 時に UNIQUE(persona_id, date, session_seq) 違反になる。
        seq=1 の新規作成は ON CONFLICT DO UPDATE で原子化し、衝突時は
        UPDATE no-op で既存行を RETURNING する。

    Note:
        呼び出し元でトランザクションを開始していることを前提とする。

    Args:
        conn: DB接続（トランザクション開始済みであること）
        session_date: セッション日付
        project: プロジェクト名
        persona_id: 人格識別子

    Returns:
        セッションのdict（id, date, session_seq, ...）
    """
    async with conn.cursor() as cur:
        # 既存セッション（最新seq）を取得
        await cur.execute(
            """
            SELECT * FROM t_sessions
            WHERE date = %s AND persona_id = %s
            ORDER BY session_seq DESC
            LIMIT 1
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

        # 未検出: seq=1 で新規作成。並行で先に作られていれば DO UPDATE no-op で
        # 既存行を RETURNING して返す（race condition 回避）。
        await cur.execute(
            """
            INSERT INTO t_sessions (persona_id, date, session_seq, project)
            VALUES (%s, %s, 1, %s)
            ON CONFLICT (persona_id, date, session_seq)
            DO UPDATE SET session_seq = t_sessions.session_seq
            RETURNING *
            """,
            (persona_id, session_date, project),
        )
        new_session = await cur.fetchone()
        logger.debug(
            "新規セッション取得/作成: id=%s, date=%s",
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
