"""recall ツール — 記憶を検索する"""
import logging
from datetime import date, datetime, timedelta

from lisanima.db import db_pool
from lisanima.repositories import message_repo, stats_repo
from lisanima.repositories._validators import (
    VALID_MODES,
    parseDateRange,
    parseSince,
    validateEmotionFilter,
)

logger = logging.getLogger(__name__)

# compact モードで返却するフィールド
_COMPACT_FIELDS = {"id", "session_date", "speaker", "content", "emotion_total", "tags", "roles"}


def _validateParams(
    limit: int,
    offset: int,
    date_from: str | None,
    date_to: str | None,
    emotion_filter: dict | None = None,
    mode: str = "default",
    since: str | None = None,
    tags: list[str] | None = None,
    tags_empty: bool = False,
    source: str | None = None,
    topic_id: list[int] | None = None,
    topics_empty: bool = False,
) -> tuple[date | None, date | None, timedelta | None]:
    """入力パラメータを検証する。

    Args:
        limit: 取得件数上限
        offset: オフセット
        date_from: 日付範囲開始
        date_to: 日付範囲終了
        emotion_filter: 感情レンジフィルタ
        mode: 検索モード
        since: 相対時間フィルタ
        tags: タグフィルタ
        tags_empty: タグなしフィルタ
        source: 発信元フィルタ
        topic_id: トピックIDフィルタ
        topics_empty: トピック未紐付けフィルタ

    Returns:
        (parsed_date_from, parsed_date_to, since_delta)

    Raises:
        ValueError: バリデーションエラー時
    """
    if limit < 1:
        raise ValueError("limit は 1 以上で指定してください")

    if offset < 0:
        raise ValueError("offset は 0 以上で指定してください")

    if mode not in VALID_MODES:
        raise ValueError(
            f"mode は {sorted(VALID_MODES)} のいずれかで指定してください: {mode}"
        )

    # since の空文字チェック
    if since is not None and since.strip() == "":
        raise ValueError("since に空文字は指定できません")

    # since と date_from は排他
    if since and date_from:
        raise ValueError("since と date_from は同時に指定できません")

    # tags と tags_empty は排他
    if tags and tags_empty:
        raise ValueError("tags と tags_empty は同時に指定できません")

    # topics_empty と topic_id は排他
    if topics_empty and topic_id:
        raise ValueError("topics_empty と topic_id は同時に指定できません")

    # source の空文字チェック
    if source is not None and source.strip() == "":
        raise ValueError("source に空文字は指定できません")

    # since の書式検証とパース（二重パース防止のため結果を返却）
    since_delta: timedelta | None = None
    if since:
        since_delta = parseSince(since)

    parsed_from, parsed_to = parseDateRange(date_from, date_to)
    validateEmotionFilter(emotion_filter)

    return parsed_from, parsed_to, since_delta


def _applyCompact(messages: list[dict]) -> list[dict]:
    """compact モード用にメッセージのフィールドを削減する。

    Args:
        messages: 元のメッセージリスト

    Returns:
        不要フィールドを除去したメッセージリスト
    """
    return [
        {k: v for k, v in msg.items() if k in _COMPACT_FIELDS}
        for msg in messages
    ]


async def recall(
    query: list[str] | None = None,
    tags: list[str] | None = None,
    speaker: str | None = None,
    project: str | None = None,
    topic_id: list[int] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    emotion_filter: dict | None = None,
    mode: str = "default",
    compact: bool = False,
    since: str | None = None,
    tags_empty: bool = False,
    topics_empty: bool = False,
    source: str | None = None,
    roles: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """記憶を検索する。

    Args:
        query: 全文検索キーワード（AND検索）
        tags: タグ名でフィルタ（AND検索）
        speaker: 発言者でフィルタ
        project: プロジェクト名でフィルタ
        topic_id: トピックIDでフィルタ（OR検索）
        date_from: 日付範囲の開始（YYYY-MM-DD）
        date_to: 日付範囲の終了（YYYY-MM-DD）
        emotion_filter: 感情値のレンジフィルタ
        mode: 検索モード（default/hot/stats）
        compact: コンパクトモード（フィールド削減）
        since: 相対時間フィルタ（例: "7d", "24h", "2w"）
        tags_empty: タグなしメッセージのみ取得
        topics_empty: トピック未紐付けメッセージのみ取得
        source: 発信元フィルタ（完全一致）
        roles: ロール名でフィルタ（AND検索）
        limit: 取得件数上限（デフォルト: 20）
        offset: オフセット（デフォルト: 0）

    Returns:
        {"total": int, "mode": str, "messages": list[dict]}
        エラー時は {"error": "ERROR_CODE", "message": "エラーメッセージ"}
    """
    # バリデーション
    try:
        _, _, since_delta = _validateParams(
            limit, offset, date_from, date_to, emotion_filter,
            mode=mode, since=since, tags=tags, tags_empty=tags_empty,
            source=source, topic_id=topic_id, topics_empty=topics_empty,
        )
    except ValueError as e:
        return {"error": "INVALID_PARAMETER", "message": str(e)}

    try:
        async with db_pool.get_connection() as conn:
            # stats モード: 統計情報を返却して早期リターン
            if mode == "stats":
                # since / since_delta から datetime を算出
                since_dt: datetime | None = None
                if since_delta:
                    since_dt = datetime.now().astimezone() - since_delta

                summary = await stats_repo.getMessageStats(conn, since=since_dt)
                tag_stats = await stats_repo.getTagStats(conn, since=since_dt)
                topic_stats = await stats_repo.getTopicStats(conn, since=since_dt)
                role_stats = await stats_repo.getRoleStats(conn, since=since_dt)

                logger.debug("recall stats完了: since=%s", since_dt)
                return {
                    "mode": "stats",
                    "summary": summary,
                    "tags": tag_stats,
                    "topics": topic_stats,
                    "roles": role_stats,
                }

            # hot モード: 複合スコアリングで上位N件を自動浮上
            if mode == "hot":
                result = await stats_repo.getHotMessages(conn, limit=limit)
                # datetimeをISO文字列に変換
                for msg in result["messages"]:
                    if msg.get("created_at"):
                        msg["created_at"] = msg["created_at"].isoformat()
                result["mode"] = "hot"
                logger.debug("recall hot完了: total=%d", result["total"])
                return result

            result = await message_repo.searchMessages(
                conn,
                query=query,
                tags=tags,
                speaker=speaker,
                project=project,
                topic_id=topic_id,
                date_from=date_from,
                date_to=date_to,
                emotion_filter=emotion_filter,
                since_delta=since_delta,
                tags_empty=tags_empty,
                topics_empty=topics_empty,
                source=source,
                roles=roles,
                limit=limit,
                offset=offset,
            )

        # datetimeをISO文字列に変換
        for msg in result["messages"]:
            if msg.get("created_at"):
                msg["created_at"] = msg["created_at"].isoformat()
            if msg.get("session_date"):
                msg["session_date"] = str(msg["session_date"])

        # compact モード適用
        if compact:
            result["messages"] = _applyCompact(result["messages"])

        result["mode"] = mode
        logger.debug("recall完了: total=%d, mode=%s, compact=%s", result["total"], mode, compact)
        return result

    except RuntimeError as e:
        logger.error("DB接続エラー: %s", e)
        return {"error": "DB_CONNECTION_ERROR", "message": str(e)}
    except Exception as e:
        logger.error("recall failed", exc_info=True)
        return {"error": "INTERNAL_ERROR", "message": "予期しないエラーが発生しました"}
