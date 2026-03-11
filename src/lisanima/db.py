"""非同期データベース接続管理（psycopg3）

MCPサーバー向けの非同期DB接続プールを提供する。
psycopg3 の AsyncConnectionPool を使い、接続の再利用と上限管理を行う。
crypto_trade_bot の async_database.py をベースに、lisanima用に調整。
"""
import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote_plus

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _load_env() -> None:
    """lisanima/.env から環境変数を読み込む。

    既に設定済みの環境変数は上書きしない（load_dotenvのデフォルト動作）。
    """
    env_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(env_path)


def get_dsn() -> str:
    """PostgreSQL接続文字列（DSN）を組み立てる。

    パスワードに特殊文字（#, @, / 等）が含まれる場合、
    URL構文が壊れるため quote_plus でパーセントエンコードする。

    Returns:
        postgresql://user:password@host:port/dbname 形式の接続文字列
    """
    _load_env()
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    dbname = os.getenv("DB_NAME", "lisanima_db")
    user = quote_plus(os.getenv("DB_USER", ""))
    password = quote_plus(os.getenv("DB_PASSWORD", ""))
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}?connect_timeout=10"


class AsyncDatabasePool:
    """非同期DB接続プール管理クラス。

    psycopg3 の AsyncConnectionPool をラップし、ライフサイクル管理を提供する。

    使用パターン:
        MCPサーバーの起動時に open()、終了時に close() を呼び出し、
        各ツールハンドラでは get_connection() で接続を取得する。
    """

    def __init__(self):
        self._pool: AsyncConnectionPool | None = None

    async def open(self) -> None:
        """接続プールを初期化して開く。"""
        dsn = get_dsn()
        self._pool = AsyncConnectionPool(
            conninfo=dsn,
            min_size=2,
            max_size=5,
            open=False,
            kwargs={
                "row_factory": dict_row,
                "autocommit": False,
                "options": "-c statement_timeout=30000",
            },
        )
        await self._pool.open()
        logger.info("非同期DB接続プール開始")

    async def close(self) -> None:
        """接続プールを閉じ、全接続を解放する。"""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("非同期DB接続プール終了")

    @asynccontextmanager
    async def get_connection(self):
        """接続プールから接続を取得する（非同期コンテキストマネージャ）。

        プール未初期化の場合は自動で初期化する（lazy init）。
        OAuth認証フローなど、MCPセッション確立前のリクエストに対応するため。

        Usage:
            async with db_pool.get_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT ...")

        Yields:
            AsyncConnection
        """
        if not self._pool:
            await self.open()
        async with self._pool.connection() as conn:
            yield conn


# シングルトンインスタンス
db_pool = AsyncDatabasePool()
