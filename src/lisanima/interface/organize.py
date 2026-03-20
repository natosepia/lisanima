"""organize ツール — タグ整理（付与・削除）"""
import logging
from datetime import date

from lisanima.db import db_pool
from lisanima.repositories import message_repo, tag_repo
from lisanima.repositories._validators import parseDateRange, validateEmotionFilter

logger = logging.getLogger(__name__)


def _validateParams(
    message_ids: list[int] | None,
    query: list[str] | None,
    tags: list[str] | None,
    speaker: str | None,
    project: str | None,
    topic_id: list[int] | None,
    date_from: str | None,
    date_to: str | None,
    emotion_filter: dict | None,
    add_tags: list[str] | None,
    remove_tags: list[str] | None,
) -> tuple[date | None, date | None]:
    """入力パラメータを検証する。

    Args:
        各パラメータはorganize関数の引数と同一

    Returns:
        (parsed_date_from, parsed_date_to)

    Raises:
        ValueError: バリデーションエラー時
    """
    # add_tags / remove_tags の両方なしは不正
    if not add_tags and not remove_tags:
        raise ValueError("add_tags または remove_tags のいずれかを指定してください")

    # add_tags と remove_tags に同一タグがあれば不正
    if add_tags and remove_tags:
        add_set = {tag_repo.normalizeTagName(t) for t in add_tags if t.strip()}
        remove_set = {tag_repo.normalizeTagName(t) for t in remove_tags if t.strip()}
        overlap = add_set & remove_set
        if overlap:
            raise ValueError(
                f"add_tags と remove_tags に同一タグがあります: {', '.join(sorted(overlap))}"
            )

    # 検索条件もmessage_idsもなしは全件操作になるため不正
    has_search = any([query, tags, speaker, project, topic_id, date_from, date_to, emotion_filter])
    if not message_ids and not has_search:
        raise ValueError(
            "message_ids または検索条件（query, tags, speaker, project, topic_id, "
            "date_from, date_to, emotion_filter）のいずれかを指定してください"
        )

    # 日付パース・emotion_filter バリデーション
    parsed_from, parsed_to = parseDateRange(date_from, date_to)
    validateEmotionFilter(emotion_filter)

    return parsed_from, parsed_to


async def organize(
    message_ids: list[int] | None = None,
    query: list[str] | None = None,
    tags: list[str] | None = None,
    speaker: str | None = None,
    project: str | None = None,
    topic_id: list[int] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    emotion_filter: dict | None = None,
    include_deleted: bool = False,
    add_tags: list[str] | None = None,
    remove_tags: list[str] | None = None,
    limit: int = 100000,
) -> dict:
    """メッセージのタグ整理を行う。

    検索条件またはID直接指定で対象メッセージを特定し、
    タグの追加・削除を一括で行う。

    Args:
        message_ids: 対象メッセージIDの直接指定
        query: 全文検索キーワード（AND検索）
        tags: 既存タグでフィルタ（AND検索）
        speaker: 発言者でフィルタ
        project: プロジェクト名でフィルタ
        topic_id: トピックIDでフィルタ（OR検索）
        date_from: 日付範囲の開始（YYYY-MM-DD）
        date_to: 日付範囲の終了（YYYY-MM-DD）
        emotion_filter: 感情値のレンジフィルタ
        include_deleted: 論理削除済みも対象にする（デフォルト: False）
        add_tags: 追加するタグ名の配列
        remove_tags: 削除するタグ名の配列
        limit: 処理件数上限（デフォルト: 100000）

    Returns:
        {"organized_count": int, "tags_added": list, "tags_removed": list}
        エラー時は {"error": "ERROR_CODE", "message": "エラーメッセージ"}
    """
    # バリデーション
    try:
        _validateParams(
            message_ids, query, tags, speaker, project, topic_id,
            date_from, date_to, emotion_filter, add_tags, remove_tags,
        )
    except ValueError as e:
        return {"error": "INVALID_PARAMETER", "message": str(e)}

    try:
        async with db_pool.get_connection() as conn:
            # 対象メッセージIDの特定
            target_ids: set[int] = set()

            # message_ids 直接指定分
            if message_ids:
                target_ids.update(message_ids)

            # 検索条件指定分
            has_search = any([query, tags, speaker, project, topic_id, date_from, date_to, emotion_filter])
            if has_search:
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
                    limit=limit,
                    offset=0,
                    include_deleted=include_deleted,
                )
                for msg in result["messages"]:
                    target_ids.add(msg["id"])

            target_id_list = list(target_ids)

            if not target_id_list:
                return {
                    "organized_count": 0,
                    "tags_added": add_tags or [],
                    "tags_removed": remove_tags or [],
                }

            async with conn.transaction():
                # add_tags 処理
                tags_added_names: list[str] = []
                if add_tags:
                    tag_records = await tag_repo.findOrCreateTags(conn, add_tags)
                    tag_ids = [t["id"] for t in tag_records]
                    await tag_repo.linkMessageTagsBatch(conn, target_id_list, tag_ids)
                    tags_added_names = [t["name"] for t in tag_records]

                # remove_tags 処理
                tags_removed_names: list[str] = []
                if remove_tags:
                    await tag_repo.unlinkMessageTagsBatch(conn, target_id_list, remove_tags)
                    tags_removed_names = [tag_repo.normalizeTagName(t) for t in remove_tags if t.strip()]

        logger.debug(
            "organize完了: count=%d, added=%s, removed=%s",
            len(target_id_list), tags_added_names, tags_removed_names,
        )

        return {
            "organized_count": len(target_id_list),
            "tags_added": tags_added_names,
            "tags_removed": tags_removed_names,
        }

    except RuntimeError as e:
        logger.error("DB接続エラー: %s", e)
        return {"error": "DB_CONNECTION_ERROR", "message": str(e)}
    except Exception as e:
        logger.error("organize failed", exc_info=True)
        return {"error": "INTERNAL_ERROR", "message": "予期しないエラーが発生しました"}
