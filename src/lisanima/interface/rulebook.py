"""rulebook ツール — ルール（what）とプロトコル（how）の参照・管理"""
import logging
from datetime import datetime

from lisanima.db import db_pool
from lisanima.repositories import protocol_repo, rulebook_repo

logger = logging.getLogger(__name__)

# 許可するアクション
_VALID_ACTIONS = {"get", "set", "retire", "list"}
_VALID_SUB_ACTIONS = {"rule", "protocol"}


def _validateParams(
    action: str,
    sub_action: str,
    key: str | None,
    content: str | None,
    seq: int | None,
) -> None:
    """入力パラメータを検証する。

    Args:
        action: 操作種別
        sub_action: 操作対象（"rule" / "protocol"）
        key: ルールキー or 手順名
        content: ルール本文 or ステップ内容
        seq: ステップ番号（protocol set時必須）

    Raises:
        ValueError: バリデーションエラー時
    """
    if action not in _VALID_ACTIONS:
        raise ValueError("action は get/set/retire/list のいずれかです")

    if sub_action not in _VALID_SUB_ACTIONS:
        raise ValueError("sub_action は rule/protocol のいずれかです")

    # 想定外の組み合わせ
    if sub_action == "protocol" and action == "retire":
        raise ValueError("想定外の操作です: retire + protocol は未提供")

    if action in ("get", "set", "retire"):
        if not key or not key.strip():
            raise ValueError("key は空にできません")

    if action == "set":
        if not content or not content.strip():
            raise ValueError("content は空にできません")
        if sub_action == "protocol":
            if seq is None:
                raise ValueError("protocol の set には seq が必須です")
            if seq < 1:
                raise ValueError("seq は 1 以上の整数です")


def _toIsoString(value: datetime | None) -> str | None:
    """datetimeをISO 8601文字列に変換する。"""
    if value is None:
        return None
    return value.isoformat()


async def rulebook(
    action: str,
    sub_action: str = "rule",
    key: str | None = None,
    content: str | None = None,
    reason: str | None = None,
    persona_id: str | None = None,
    seq: int | None = None,
    exportable: bool = False,
) -> dict:
    """ルールブック（what）とプロトコル（how）の参照・設定・廃止を行う。

    sub_action="rule" は従来のルール管理（イミュータブル追記、バージョン管理）、
    sub_action="protocol" は手順管理（UPSERT、ステップ単位）を行う。

    Args:
        action: 操作種別 ("get" / "set" / "retire" / "list")
        sub_action: 操作対象 ("rule"（デフォルト）/ "protocol")
        key: rule のルールキー / protocol の手順名（get/set/retire時必須）
        content: rule のルール本文 / protocol のステップ内容（set時必須）
        reason: 変更理由（rule のみ）
        persona_id: ペルソナID（rule のみ。デフォルト '*'）
        seq: ステップ番号（protocol の set 時必須）
        exportable: .claude/rules/ エクスポート対象フラグ（protocol の set 時）

    Returns:
        操作結果のdict
        エラー時は {"error": "ERROR_CODE", "message": "エラーメッセージ"}
    """
    # rule の persona_id デフォルト値変換（list はNoneで全件取得を許容）
    if sub_action == "rule" and persona_id is None and action != "list":
        persona_id = "*"

    # バリデーション
    try:
        _validateParams(action, sub_action, key, content, seq)
    except ValueError as e:
        return {"error": "INVALID_PARAMETER", "message": str(e)}

    try:
        async with db_pool.get_connection() as conn:
            if sub_action == "rule":
                return await _dispatchRule(
                    conn, action, key, content, reason, persona_id,
                )
            else:
                return await _dispatchProtocol(
                    conn, action, key, content, seq, exportable,
                )

    except RuntimeError as e:
        logger.error("DB接続エラー: %s", e)
        return {"error": "DB_CONNECTION_ERROR", "message": str(e)}
    except Exception:
        logger.error("rulebook failed", exc_info=True)
        return {"error": "INTERNAL_ERROR", "message": "予期しないエラーが発生しました"}


# ============================================================
# rule ディスパッチ
# ============================================================

async def _dispatchRule(
    conn,
    action: str,
    key: str | None,
    content: str | None,
    reason: str | None,
    persona_id: str | None,
) -> dict:
    """sub_action="rule" のアクション分岐。"""
    if action == "get":
        return await _handleGet(conn, key)
    elif action == "set":
        return await _handleSet(conn, key, content, reason, persona_id)
    elif action == "retire":
        return await _handleRetire(conn, key)
    else:
        return await _handleList(conn, persona_id)


async def _handleGet(conn, path: str) -> dict:
    """rule getアクションの処理。"""
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
    """rule setアクションの処理。"""
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
    """rule retireアクションの処理。"""
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
    """rule listアクションの処理。"""
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


# ============================================================
# protocol ディスパッチ
# ============================================================

async def _dispatchProtocol(
    conn,
    action: str,
    key: str | None,
    content: str | None,
    seq: int | None,
    exportable: bool,
) -> dict:
    """sub_action="protocol" のアクション分岐。"""
    if action == "get":
        return await _handleProtocolGet(conn, key)
    elif action == "set":
        return await _handleProtocolSet(conn, key, seq, content, exportable)
    else:
        # action == "list" （retireはバリデーションで除外済み）
        return await _handleProtocolList(conn)


async def _handleProtocolGet(conn, protocol_name: str) -> dict:
    """protocol getアクションの処理。"""
    rows = await protocol_repo.getProtocol(conn, protocol_name)
    if not rows:
        return {
            "error": "NOT_FOUND",
            "message": f"protocol_name='{protocol_name}' の手順が見つかりません",
        }

    steps = []
    for row in rows:
        steps.append({
            "seq": row["seq"],
            "content": row["content"],
            "exportable": row["exportable"],
            "updated_at": _toIsoString(row.get("updated_at")),
        })

    return {
        "protocol_name": protocol_name,
        "steps": steps,
    }


async def _handleProtocolSet(
    conn,
    protocol_name: str,
    seq: int,
    content: str,
    exportable: bool,
) -> dict:
    """protocol setアクションの処理（UPSERT）。"""
    async with conn.transaction():
        row = await protocol_repo.setProtocol(
            conn, protocol_name, seq, content, exportable,
        )

    logger.debug(
        "protocol set完了: protocol_name=%s, seq=%d",
        protocol_name, seq,
    )
    return {
        "protocol_name": row["protocol_name"],
        "seq": row["seq"],
        "status": "saved",
    }


async def _handleProtocolList(conn) -> dict:
    """protocol listアクションの処理。"""
    rows = await protocol_repo.listProtocols(conn)

    protocols = [
        {"protocol_name": row["protocol_name"], "step_count": row["step_count"]}
        for row in rows
    ]

    logger.debug("protocol list完了: count=%d", len(protocols))
    return {"protocols": protocols}
