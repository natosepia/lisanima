"""interface 層共通のエラーハンドリングデコレータ

interface配下のツール関数で重複していた以下のexcept節を集約する:
  - RuntimeError → DB_CONNECTION_ERROR
  - LookupError → NOT_FOUND
  - Exception → INTERNAL_ERROR

INVALID_PARAMETER 系は各関数の入力バリデーション部に残す（ValueErrorは
デコレータで一括変換しない方針: tool固有メッセージを優先するため）。
"""
import functools
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

_R = TypeVar("_R", bound=dict)


def handleInterfaceErrors(tool_name: str) -> Callable[[Callable[..., Awaitable[_R]]], Callable[..., Awaitable[dict]]]:
    """interface tool関数を共通エラーレスポンスでラップする。

    LookupError は NOT_FOUND として、RuntimeError は DB_CONNECTION_ERROR として、
    それ以外のExceptionはスタックトレースをloggingした上で INTERNAL_ERROR として返却する。

    Args:
        tool_name: ログ識別用のtool名（"recall" / "remember" など）

    Returns:
        装飾済みの非同期関数
    """
    def decorator(func: Callable[..., Awaitable[_R]]) -> Callable[..., Awaitable[dict]]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> dict:
            try:
                return await func(*args, **kwargs)
            except LookupError as e:
                return {"error": "NOT_FOUND", "message": str(e)}
            except RuntimeError as e:
                logger.error("DB接続エラー: %s", e)
                return {"error": "DB_CONNECTION_ERROR", "message": str(e)}
            except Exception:
                logger.error("%s failed", tool_name, exc_info=True)
                return {"error": "INTERNAL_ERROR", "message": "予期しないエラーが発生しました"}
        return wrapper
    return decorator
