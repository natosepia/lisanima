"""PIN認証エンドポイント

/auth/pin エンドポイントを提供する。
authorize() からリダイレクトされたユーザーにPIN入力フォームを表示し、
PIN検証成功で認可コードを発行してクライアントにリダイレクトする。
"""
import logging
import os
import time
from html import escape
from pathlib import Path
from urllib.parse import urlencode

import bcrypt
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from lisanima.db import db_pool
from lisanima.repositories import oauth_repo

logger = logging.getLogger(__name__)

# ブルートフォース対策: 失敗回数/ロックアウト
_MAX_FAILURES = 5
_LOCKOUT_SECONDS = 30
_failure_count = 0
_lockout_until = 0.0

# テンプレートキャッシュ
_template_cache: str | None = None


def _loadTemplate() -> str:
    """PIN入力フォームHTMLテンプレートを読み込む。"""
    global _template_cache
    if _template_cache is None:
        tmpl_path = Path(__file__).parent / "templates" / "pin.html"
        _template_cache = tmpl_path.read_text(encoding="utf-8")
    return _template_cache


def _getPinHash() -> str:
    """環境変数からPINハッシュを取得する。

    Returns:
        bcryptハッシュ文字列

    Raises:
        RuntimeError: OAUTH_PIN_HASH が未設定の場合
    """
    pin_hash = os.getenv("OAUTH_PIN_HASH")
    if not pin_hash:
        raise RuntimeError("OAUTH_PIN_HASH が設定されていません")
    return pin_hash


def _verifyPin(pin: str) -> bool:
    """PINを検証する。

    Args:
        pin: ユーザー入力のPIN

    Returns:
        一致すればTrue
    """
    pin_hash = _getPinHash()
    return bcrypt.checkpw(pin.encode("utf-8"), pin_hash.encode("utf-8"))


def _checkLockout() -> bool:
    """ロックアウト中かどうかを判定する。

    Returns:
        ロックアウト中ならTrue
    """
    global _failure_count, _lockout_until

    if _lockout_until > 0 and time.monotonic() < _lockout_until:
        return True

    # ロックアウト期限切れならリセット
    if _lockout_until > 0 and time.monotonic() >= _lockout_until:
        _failure_count = 0
        _lockout_until = 0.0

    return False


def _recordFailure() -> None:
    """PIN検証失敗を記録し、閾値超過でロックアウトを設定する。"""
    global _failure_count, _lockout_until

    _failure_count += 1
    if _failure_count >= _MAX_FAILURES:
        _lockout_until = time.monotonic() + _LOCKOUT_SECONDS
        logger.warning("PIN認証ロックアウト: %d秒間", _LOCKOUT_SECONDS)


def _resetFailures() -> None:
    """PIN検証成功時に失敗カウンタをリセットする。"""
    global _failure_count, _lockout_until
    _failure_count = 0
    _lockout_until = 0.0


async def handlePinGet(request: Request) -> Response:
    """PIN入力フォームを表示する（GET /auth/pin）。

    Args:
        request: Starletteリクエスト（query: session_id）

    Returns:
        PIN入力フォームHTML
    """
    session_id = request.query_params.get("session_id", "")
    if not session_id:
        return HTMLResponse("<h1>不正なリクエストです</h1>", status_code=400)

    # セッション存在確認
    async with db_pool.get_connection() as conn:
        session = await oauth_repo.loadAuthSession(conn, session_id)
    if session is None:
        return HTMLResponse("<h1>セッションが期限切れまたは不正です</h1>", status_code=400)

    template = _loadTemplate()
    html = template.replace("{{session_id}}", escape(session_id)).replace("{{error}}", "")
    return HTMLResponse(html)


async def handlePinPost(request: Request) -> Response:
    """PIN検証を行い、成功時に認可コードを発行してリダイレクトする（POST /auth/pin）。

    Args:
        request: Starletteリクエスト（form: session_id, pin, action）

    Returns:
        成功: redirect_uri?code=xxx&state=xxx へリダイレクト
        失敗: PIN入力フォームにエラー表示
    """
    form = await request.form()
    session_id = form.get("session_id", "")
    pin = form.get("pin", "")
    action = form.get("action", "")

    if not session_id:
        return HTMLResponse("<h1>不正なリクエストです</h1>", status_code=400)

    # セッション取得
    async with db_pool.get_connection() as conn:
        session = await oauth_repo.loadAuthSession(conn, session_id)
    if session is None:
        return HTMLResponse("<h1>セッションが期限切れまたは不正です</h1>", status_code=400)

    # 拒否ボタン
    if action == "deny":
        redirect_uri = session["redirect_uri"]
        params = {"error": "access_denied", "error_description": "ユーザーが認可を拒否しました"}
        if session.get("state"):
            params["state"] = session["state"]

        # セッション削除
        async with db_pool.get_connection() as conn:
            async with conn.transaction():
                await oauth_repo.deleteAuthSession(conn, session_id)

        return RedirectResponse(
            url=f"{redirect_uri}?{urlencode(params)}",
            status_code=302,
        )

    # ロックアウトチェック
    if _checkLockout():
        template = _loadTemplate()
        html = template.replace("{{session_id}}", escape(session_id)).replace(
            "{{error}}", "認証試行回数を超過しました。しばらくお待ちください。"
        )
        return HTMLResponse(html, status_code=429)

    # PIN検証
    if not _verifyPin(pin):
        _recordFailure()
        remaining = _MAX_FAILURES - _failure_count
        error_msg = f"PINが正しくありません（残り{remaining}回）" if remaining > 0 else "ロックアウトされました。しばらくお待ちください。"
        template = _loadTemplate()
        html = template.replace("{{session_id}}", escape(session_id)).replace(
            "{{error}}", error_msg,
        )
        return HTMLResponse(html, status_code=401)

    # PIN検証成功
    _resetFailures()

    # 認可コード発行
    async with db_pool.get_connection() as conn:
        async with conn.transaction():
            code = await oauth_repo.saveAuthCode(
                conn,
                client_id=session["client_id"],
                redirect_uri=session["redirect_uri"],
                redirect_uri_provided_explicitly=session["redirect_uri_provided_explicitly"],
                code_challenge=session["code_challenge"],
                code_challenge_method=session["code_challenge_method"],
                scopes=session["scopes"],
                resource=session.get("resource"),
            )
            # 認可セッション削除（使い切り）
            await oauth_repo.deleteAuthSession(conn, session_id)

    # redirect_uri にリダイレクト
    redirect_uri = session["redirect_uri"]
    params = {"code": code}
    if session.get("state"):
        params["state"] = session["state"]

    logger.info("PIN認証成功 → 認可コード発行: client_id=%s", session["client_id"])
    return RedirectResponse(
        url=f"{redirect_uri}?{urlencode(params)}",
        status_code=302,
    )
