"""ルールブックリポジトリ

m_rulebooks テーブルおよび v_active_rulebooks ビューへの操作を提供する。
"""
import logging

from psycopg import AsyncConnection

logger = logging.getLogger(__name__)

# 新規pathのデフォルトlevel
_DEFAULT_LEVEL = 4


async def getRulebook(
    conn: AsyncConnection,
    path: str,
) -> dict | None:
    """指定pathに一致するアクティブなルールを取得する。

    v_active_rulebooks（最新version かつ is_retired=FALSE）から検索する。

    Args:
        conn: DB接続
        path: ルールのパス（Materialized Path）

    Returns:
        ルールのdict、見つからない場合はNone
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT * FROM v_active_rulebooks
            WHERE path = %s
            """,
            (path,),
        )
        row = await cur.fetchone()

    if row:
        logger.debug("ルール取得: path=%s, version=%s", path, row["version"])
    else:
        logger.debug("ルール未検出: path=%s", path)
    return row


async def setRulebook(
    conn: AsyncConnection,
    path: str,
    content: str,
    reason: str = "none",
    persona_id: str = "*",
) -> dict:
    """ルールをイミュータブル追記で保存する。

    既存pathの最新versionを取得し、version+1でINSERTする。
    既存レコードが is_editable=FALSE の場合は書き換えを拒否する。
    初回（該当パスが存在しない場合）はversion=1で作成する。

    Args:
        conn: DB接続
        path: ルールのパス（Materialized Path）
        content: ルール内容
        reason: 変更理由
        persona_id: 人格識別子（新規path作成時のデフォルト: '*'）

    Returns:
        作成したルールのdict
        is_editable=FALSEの場合は {"error": "PERMISSION_DENIED"} を含むdict

    """
    async with conn.cursor() as cur:
        # 実テーブルから最新versionのレコードを取得
        await cur.execute(
            """
            SELECT version, level, is_editable, persona_id
            FROM m_rulebooks
            WHERE path = %s
            ORDER BY version DESC
            LIMIT 1
            """,
            (path,),
        )
        existing = await cur.fetchone()

        if existing:
            # is_editableチェック
            if not existing["is_editable"]:
                logger.debug("編集不可ルール: path=%s", path)
                return {
                    "error": "PERMISSION_DENIED",
                    "message": f"path='{path}' は編集不可（is_editable=FALSE）です",
                }
            new_version = existing["version"] + 1
            level = existing["level"]
            # 既存レコードのpersona_idを引き継ぐ
            persona_id = existing["persona_id"]
        else:
            new_version = 1
            level = _DEFAULT_LEVEL

        await cur.execute(
            """
            INSERT INTO m_rulebooks (path, version, level, content, reason, persona_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (path, new_version, level, content, reason, persona_id),
        )
        row = await cur.fetchone()

    logger.debug(
        "ルール保存: path=%s, version=%s",
        path, new_version,
    )
    return row


async def retireRulebook(
    conn: AsyncConnection,
    path: str,
) -> dict:
    """ルールの最新版をリタイアする（is_retired=TRUE）。

    m_rulebooks実テーブルの最新version（pathでMAX(version)）を更新する。
    is_editable=FALSEのルールはリタイア不可。

    Args:
        conn: DB接続
        path: ルールのパス（Materialized Path）

    Returns:
        結果を示すdict:
        - 成功時: {"status": "retired", "row": 更新後のdict}
        - 存在しない場合: {"status": "not_found", "row": None}
        - 既にリタイア済み: {"status": "already_retired", "row": 既存のdict}
        - 編集不可: {"status": "permission_denied", "row": 既存のdict}
    """
    async with conn.cursor() as cur:
        # 最新versionのレコードを取得
        await cur.execute(
            """
            SELECT * FROM m_rulebooks
            WHERE path = %s
            ORDER BY version DESC
            LIMIT 1
            """,
            (path,),
        )
        row = await cur.fetchone()

        if not row:
            logger.debug("リタイア対象未検出: path=%s", path)
            return {"status": "not_found", "row": None}

        if not row["is_editable"]:
            logger.debug("編集不可ルール: path=%s", path)
            return {"status": "permission_denied", "row": dict(row)}

        if row["is_retired"]:
            logger.debug(
                "既にリタイア済み: path=%s, version=%s",
                path, row["version"],
            )
            return {"status": "already_retired", "row": dict(row)}

        # is_retiredをTRUEに更新（複合PK: path + version）
        await cur.execute(
            """
            UPDATE m_rulebooks SET is_retired = TRUE
            WHERE path = %s AND version = %s
            RETURNING *
            """,
            (row["path"], row["version"]),
        )
        updated = await cur.fetchone()

    logger.debug(
        "ルールリタイア: path=%s, version=%s",
        path, updated["version"],
    )
    return {"status": "retired", "row": updated}


async def listRulebooks(
    conn: AsyncConnection,
    persona_id: str | None = None,
) -> list[dict]:
    """アクティブなルール一覧を取得する。

    v_active_rulebooks から取得する。
    ORDER BY path でMaterialized Pathの階層順にソートする。

    Args:
        conn: DB接続
        persona_id: フィルタ条件（None=全件, '*'=全ペルソナ共通のみ, その他=指定値のみ）

    Returns:
        ルールのdictリスト
    """
    async with conn.cursor() as cur:
        if persona_id is None:
            await cur.execute(
                "SELECT * FROM v_active_rulebooks ORDER BY path"
            )
        else:
            await cur.execute(
                """
                SELECT * FROM v_active_rulebooks
                WHERE persona_id = %s
                ORDER BY path
                """,
                (persona_id,),
            )
        rows = await cur.fetchall()

    logger.debug("ルール一覧取得: persona_id=%s, count=%d", persona_id, len(rows))
    return rows
