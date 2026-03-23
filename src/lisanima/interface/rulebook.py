"""rulebook ツール — ルールの参照・設定・廃止・一覧"""
import logging
from datetime import datetime

from lisanima.db import db_pool
from lisanima.repositories import rulebook_repo

logger = logging.getLogger(__name__)

# 許可するアクション
_VALID_ACTIONS = {"get", "set", "retire", "list"}


def _validateParams(
    action: str,
    key: str | None,
    content: str | None,
) -> None:
    """入力パラメータを検証する。

    Args:
        action: 操作種別
        key: ルールキー（内部ではpathとして扱う）
        content: ルール本文

    Raises:
        ValueError: バリデーションエラー時
    """
    if action not in _VALID_ACTIONS:
        raise ValueError("action は get/set/retire/list のいずれかです")

    if action in ("get", "set", "retire"):
        if not key or not key.strip():
            raise ValueError("key は空にできません")

    if action == "set":
        if not content or not content.strip():
            raise ValueError("content は空にできません")


def _toIsoString(value: datetime | None) -> str | None:
    """datetimeをISO 8601文字列に変換する。"""
    if value is None:
        return None
    return value.isoformat()


async def rulebook(
    action: str,
    key: str | None = None,
    content: str | None = None,
    reason: str | None = None,
    persona_id: str | None = None,
) -> dict:
    """ルールブックの参照・設定・廃止・一覧を行う。

    イミュータブル追記型で、バージョン管理される。
    最新かつ有効なルールのみを取得する。
    MCPツール定義の引数名 key は内部で path として扱う。

    Args:
        action: 操作種別 ("get" / "set" / "retire" / "list")
        key: ルールキー（内部ではpathとして使用。get/set/retire時必須）
        content: ルール本文（set時必須）
        reason: 変更理由
        persona_id: ペルソナID（デフォルト: '*' = 全ペルソナ共通）

    Returns:
        操作結果のdict
        エラー時は {"error": "ERROR_CODE", "message": "エラーメッセージ"}
    """
    # None→デフォルト値変換（get/set/retire時のみ。listはNoneで全件取得）
    if persona_id is None and action != "list":
        persona_id = "*"

    # バリデーション
    try:
        _validateParams(action, key, content)
    except ValueError as e:
        return {"error": "INVALID_PARAMETER", "message": str(e)}

    try:
        async with db_pool.get_connection() as conn:
            if action == "get":
                return await _handleGet(conn, key)
            elif action == "set":
                return await _handleSet(conn, key, content, reason, persona_id)
            elif action == "retire":
                return await _handleRetire(conn, key)
            else:
                return await _handleList(conn, persona_id)

    except RuntimeError as e:
        logger.error("DB接続エラー: %s", e)
        return {"error": "DB_CONNECTION_ERROR", "message": str(e)}
    except Exception:
        logger.error("rulebook failed", exc_info=True)
        return {"error": "INTERNAL_ERROR", "message": "予期しないエラーが発生しました"}


async def _handleGet(conn, path: str) -> dict:
    """getアクションの処理。"""
    row = await rulebook_repo.getRulebook(conn, path)
    if not row:
        return {
            "error": "NOT_FOUND",
            "message": f"path='{path}' のルールが見つかりません",
        }
    return {
        "path": row["path"],
        "content": row["content"],
        "version": row["version"],
        "level": row["level"],
        "is_editable": row["is_editable"],
        "persona_id": row["persona_id"],
        "created_at": _toIsoString(row.get("created_at")),
    }


async def _handleSet(
    conn, path: str, content: str, reason: str | None, persona_id: str,
) -> dict:
    """setアクションの処理。"""
    async with conn.transaction():
        row = await rulebook_repo.setRulebook(
            conn, path, content,
            reason=reason or "none",
            persona_id=persona_id,
        )

    # is_editableチェックによる拒否をリポジトリから受け取った場合
    if "error" in row:
        return row

    logger.debug("rulebook set完了: path=%s, version=%s", path, row["version"])
    return {
        "path": row["path"],
        "content": row["content"],
        "version": row["version"],
        "level": row["level"],
        "is_editable": row["is_editable"],
        "persona_id": row["persona_id"],
        "status": "saved",
    }


async def _handleRetire(conn, path: str) -> dict:
    """retireアクションの処理。"""
    async with conn.transaction():
        result = await rulebook_repo.retireRulebook(conn, path)

    status = result["status"]
    if status == "not_found":
        return {
            "error": "NOT_FOUND",
            "message": f"path='{path}' のルールが見つかりません",
        }
    if status == "already_retired":
        return {
            "error": "NOT_FOUND",
            "message": f"path='{path}' は既にリタイア済みです",
        }
    if status == "permission_denied":
        return {
            "error": "PERMISSION_DENIED",
            "message": f"path='{path}' は編集不可（is_editable=FALSE）です",
        }

    return {
        "path": path,
        "persona_id": result["row"]["persona_id"],
        "status": "retired",
    }


async def _handleList(conn, persona_id: str | None) -> dict:
    """listアクションの処理。"""
    rows = await rulebook_repo.listRulebooks(conn, persona_id)

    rules = []
    for row in rows:
        rule = dict(row)
        # datetimeをISO文字列に変換
        if rule.get("created_at"):
            rule["created_at"] = _toIsoString(rule["created_at"])
        rules.append(rule)

    logger.debug("rulebook list完了: count=%d", len(rules))
    return {"rules": rules}
