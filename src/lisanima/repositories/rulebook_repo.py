"""ルールブックリポジトリ

t_rulebooks テーブルおよび v_active_rulebooks ビューへの操作を提供する。
"""
import logging

from psycopg import AsyncConnection

logger = logging.getLogger(__name__)


async def getRulebook(
    conn: AsyncConnection,
    key: str,
    persona_id: str = "*",
) -> dict | None:
    """指定keyとpersona_idに一致するアクティブなルールを取得する。

    v_active_rulebooks（最新version かつ is_retired=FALSE）から検索する。

    Args:
        conn: DB接続
        key: ルールのキー
        persona_id: 人格識別子（デフォルト: '*' = 全ペルソナ共通）

    Returns:
        ルールのdict、見つからない場合はNone
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT * FROM v_active_rulebooks
            WHERE key = %s AND persona_id = %s
            """,
            (key, persona_id),
        )
        row = await cur.fetchone()

    if row:
        logger.debug("ルール取得: key=%s, persona_id=%s, version=%s", key, persona_id, row["version"])
    else:
        logger.debug("ルール未検出: key=%s, persona_id=%s", key, persona_id)
    return row


async def setRulebook(
    conn: AsyncConnection,
    key: str,
    content: str,
    reason: str = "none",
    persona_id: str = "*",
) -> dict:
    """ルールをイミュータブル追記で保存する。

    既存の同key+persona_idの最新versionを取得し、version+1でINSERTする。
    初回（該当キーが存在しない場合）はversion=1で作成する。

    Args:
        conn: DB接続
        key: ルールのキー
        content: ルール内容
        reason: 変更理由
        persona_id: 人格識別子（デフォルト: '*' = 全ペルソナ共通）

    Returns:
        作成したルールのdict
    """
    async with conn.cursor() as cur:
        # 実テーブルから最新versionを取得
        await cur.execute(
            """
            SELECT COALESCE(MAX(version), 0) AS max_version
            FROM t_rulebooks
            WHERE key = %s AND persona_id = %s
            """,
            (key, persona_id),
        )
        max_version = (await cur.fetchone())["max_version"]
        new_version = max_version + 1

        await cur.execute(
            """
            INSERT INTO t_rulebooks (key, content, version, reason, persona_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (key, content, new_version, reason, persona_id),
        )
        row = await cur.fetchone()

    logger.debug(
        "ルール保存: key=%s, persona_id=%s, version=%s",
        key, persona_id, new_version,
    )
    return row


async def retireRulebook(
    conn: AsyncConnection,
    key: str,
    persona_id: str = "*",
) -> dict:
    """ルールの最新版をリタイアする（is_retired=TRUE）。

    t_rulebooks実テーブルの最新version（key+persona_idでMAX(version)）を更新する。

    Args:
        conn: DB接続
        key: ルールのキー
        persona_id: 人格識別子（デフォルト: '*' = 全ペルソナ共通）

    Returns:
        結果を示すdict:
        - 成功時: {"status": "retired", "row": 更新後のdict}
        - 存在しない場合: {"status": "not_found", "row": None}
        - 既にリタイア済み: {"status": "already_retired", "row": 既存のdict}
    """
    async with conn.cursor() as cur:
        # 最新versionのレコードを取得
        await cur.execute(
            """
            SELECT * FROM t_rulebooks
            WHERE key = %s AND persona_id = %s
            ORDER BY version DESC
            LIMIT 1
            """,
            (key, persona_id),
        )
        row = await cur.fetchone()

        if not row:
            logger.debug("リタイア対象未検出: key=%s, persona_id=%s", key, persona_id)
            return {"status": "not_found", "row": None}

        if row["is_retired"]:
            logger.debug(
                "既にリタイア済み: key=%s, persona_id=%s, version=%s",
                key, persona_id, row["version"],
            )
            return {"status": "already_retired", "row": dict(row)}

        # is_retiredをTRUEに更新
        await cur.execute(
            """
            UPDATE t_rulebooks SET is_retired = TRUE
            WHERE id = %s
            RETURNING *
            """,
            (row["id"],),
        )
        updated = await cur.fetchone()

    logger.debug(
        "ルールリタイア: key=%s, persona_id=%s, version=%s",
        key, persona_id, updated["version"],
    )
    return {"status": "retired", "row": updated}


async def listRulebooks(
    conn: AsyncConnection,
    persona_id: str | None = None,
) -> list[dict]:
    """アクティブなルール一覧を取得する。

    v_active_rulebooks から取得する。

    Args:
        conn: DB接続
        persona_id: フィルタ条件（None=全件, '*'=全ペルソナ共通のみ, その他=指定値のみ）

    Returns:
        ルールのdictリスト
    """
    async with conn.cursor() as cur:
        if persona_id is None:
            await cur.execute(
                "SELECT * FROM v_active_rulebooks ORDER BY key, persona_id"
            )
        else:
            await cur.execute(
                """
                SELECT * FROM v_active_rulebooks
                WHERE persona_id = %s
                ORDER BY key
                """,
                (persona_id,),
            )
        rows = await cur.fetchall()

    logger.debug("ルール一覧取得: persona_id=%s, count=%d", persona_id, len(rows))
    return rows
