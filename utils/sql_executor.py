"""SQL実行ユーティリティ

SQLファイルまたは任意のSQL文をPostgreSQLに対して実行する。
lisanima の db.py (get_dsn()) を使用するため、接続情報は .env 経由で解決される。
同期接続（psycopg3）を使用する。

実行パターン:
    1. SQLファイルまたは文字列からSQL文を取得する
    2. psycopg.connect() でDB接続を取得する
    3. SELECT文の場合は fetchall() で結果を取得し表形式で出力する
    4. DDL/DML の場合は execute() + commit() で確定する
    5. 失敗時は rollback() を行う
    6. finally で必ず接続を close() する
    このパターンにより、エラー発生時もDBが不整合な状態にならない。
"""
import sys
from pathlib import Path

import psycopg

# lisanima の db.py から DSN 取得関数を流用
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from lisanima.db import get_dsn


# SQLファイルの配置ディレクトリ
SQL_DIR = Path(__file__).parent.parent / "sql"


def _getConnection() -> psycopg.Connection:
    """同期DB接続を取得する。

    Returns:
        psycopg.Connection
    """
    return psycopg.connect(get_dsn(), autocommit=False)


def _isSelect(sql: str) -> bool:
    """SQL文がSELECT文かどうかを判定する。

    先頭の空白・改行を除去し、SELECT で始まるかを確認する。

    Args:
        sql: 判定対象のSQL文

    Returns:
        SELECT文であれば True
    """
    return sql.strip().upper().startswith("SELECT")


def _printResult(cursor: psycopg.Cursor) -> None:
    """SELECT結果をpsql風の表形式で出力する。

    カラム名をヘッダとして表示し、区切り線で区切った後にデータ行を出力する。

    Args:
        cursor: 実行済みカーソル（description と fetchall が利用可能）
    """
    if cursor.description is None:
        return

    rows = cursor.fetchall()
    columns = [desc.name for desc in cursor.description]

    # 各カラムの最大幅を算出（ヘッダとデータの両方を考慮）
    widths: list[int] = []
    for i, col in enumerate(columns):
        max_w = len(col)
        for row in rows:
            val = str(row[i]) if row[i] is not None else ""
            max_w = max(max_w, len(val))
        widths.append(max_w)

    # ヘッダ出力
    header = " | ".join(col.ljust(w) for col, w in zip(columns, widths))
    separator = "-+-".join("-" * w for w in widths)
    print(f" {header}")
    print(f"-{separator}-")

    # データ行出力
    for row in rows:
        line = " | ".join(
            (str(v) if v is not None else "").ljust(w)
            for v, w in zip(row, widths)
        )
        print(f" {line}")

    print(f"({len(rows)} rows)")


def executeSql(sql: str, label: str = "SQL") -> None:
    """SQL文を実行する。

    SELECT文の場合は結果を表形式で出力する。
    DDL/DML の場合は commit して確定する。

    Args:
        sql: 実行するSQL文
        label: ログ出力用のラベル（ファイル名など）

    Raises:
        psycopg.Error: SQL実行エラー時
    """
    conn = _getConnection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        if _isSelect(sql):
            _printResult(cur)
        else:
            conn.commit()
        print(f"[OK] {label}")
        cur.close()
    except Exception as e:
        conn.rollback()
        print(f"[NG] {label}: {e}")
        raise
    finally:
        conn.close()


def executeSqlFile(filepath: Path) -> None:
    """指定されたSQLファイルを読み込んで実行する。

    Args:
        filepath: 実行するSQLファイルのパス

    Raises:
        FileNotFoundError: ファイルが存在しない場合
        psycopg.Error: SQL実行エラー時
    """
    if not filepath.exists():
        raise FileNotFoundError(f"SQLファイルが見つかりません: {filepath}")

    sql = filepath.read_text(encoding="utf-8")
    executeSql(sql, label=filepath.name)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python utils/sql_executor.py <command>")
        print("  file <path>  : 指定SQLファイル実行")
        print('  exec "<SQL>" : 任意SQL実行')
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "file" and len(sys.argv) >= 3:
        executeSqlFile(Path(sys.argv[2]))
    elif cmd == "exec" and len(sys.argv) >= 3:
        executeSql(sys.argv[2], label="exec")
    else:
        print(f"不明なコマンド: {cmd}")
        sys.exit(1)
