"""m_rulebooks テーブルと Markdown の相互変換ユーティリティ

Materialized Path 構造のルールブックデータを Markdown に変換（デコード）し、
Markdown からルールブックレコードに逆変換（エンコード）する。
DB接続不要の純粋なデータ変換モジュール。
"""
from __future__ import annotations

import re
from typing import TypedDict


class RulebookRecord(TypedDict, total=False):
    """m_rulebooks テーブルの1レコードに対応する辞書型。

    エンコーダは path, level, content のみ設定する。
    """
    path: str
    version: int
    level: int
    content: str
    reason: str | None
    is_retired: bool
    is_editable: bool
    persona_id: str | None


def decode(records: list[dict]) -> str:
    """m_rulebooks レコード群を Markdown 文字列に変換する。

    Args:
        records: m_rulebooks のレコードリスト。path 昇順でソートされる。

    Returns:
        Markdown 文字列
    """
    # path 昇順にソート（数値比較のため各セグメントを int 化）
    sorted_records = sorted(records, key=lambda r: _pathSortKey(r["path"]))

    lines: list[str] = []
    for rec in sorted_records:
        level: int = rec["level"]
        content: str = rec["content"]

        if level <= 3:
            # Lv1〜3 は見出し
            prefix = "#" * level
            lines.append(f"{prefix} {content}")
            lines.append("")
        else:
            # Lv4+ は本文テキスト（見出しなし）
            lines.append(content)
            lines.append("")

    # 末尾の余分な空行を1つに整理
    result = "\n".join(lines).rstrip("\n") + "\n"
    return result


def encode(markdown: str) -> list[RulebookRecord]:
    """Markdown 文字列を m_rulebooks レコードリストに変換する。

    見出しレベルに応じて path を自動採番する。
    見出し配下の本文は Lv4 レコードとして生成する。

    Note:
        - 最初の見出しが現れる前の本文行は無視される
        - 1つの見出し配下の複数段落は1つのLv4レコードに結合される
        - 本文の末尾空行は strip される（ラウンドトリップで消失）

    Args:
        markdown: 変換対象の Markdown 文字列

    Returns:
        m_rulebooks に投入可能な辞書のリスト（path, level, content を含む）
    """
    lines = markdown.split("\n")
    records: list[RulebookRecord] = []

    # 各レベルの現在カウンタ（最大4階層: Lv1〜Lv3の見出し + Lv4の本文）
    counters = [0, 0, 0, 0]
    # 本文蓄積バッファ
    bodyLines: list[str] = []
    # 現在の見出しレベル（本文をぶら下げる先）
    currentHeadingLevel: int = 0

    # 見出しパターン: 行頭の # を検出
    headingPattern = re.compile(r"^(#{1,3})\s+(.+)$")

    def _flushBody() -> None:
        """蓄積された本文を Lv4 レコードとして出力する。"""
        nonlocal bodyLines
        if not bodyLines:
            return
        text = "\n".join(bodyLines).strip()
        if not text:
            bodyLines = []
            return

        bodyLevel = currentHeadingLevel + 1
        if bodyLevel > len(counters):
            raise ValueError(
                f"本文の階層が上限({len(counters)})を超えています: "
                f"level={bodyLevel}, path prefix="
                f"{'.' .join(str(counters[i]) for i in range(currentHeadingLevel))}"
            )
        counters[bodyLevel - 1] += 1
        # bodyLevel 以降のカウンタをリセット
        for i in range(bodyLevel, len(counters)):
            counters[i] = 0

        path = ".".join(str(counters[i]) for i in range(bodyLevel))
        records.append(RulebookRecord(
            path=path,
            level=bodyLevel,
            content=text,
        ))
        bodyLines = []

    for line in lines:
        match = headingPattern.match(line)
        if match:
            # 先に蓄積中の本文をフラッシュ
            _flushBody()

            level = len(match.group(1))
            title = match.group(2).strip()

            # カウンタ更新: 該当レベルを+1、下位レベルをリセット
            counters[level - 1] += 1
            for i in range(level, len(counters)):
                counters[i] = 0

            path = ".".join(str(counters[i]) for i in range(level))
            records.append(RulebookRecord(
                path=path,
                level=level,
                content=title,
            ))
            currentHeadingLevel = level
        else:
            # 見出しでない行は本文として蓄積
            if currentHeadingLevel > 0:
                bodyLines.append(line)

    # 最後の本文をフラッシュ
    _flushBody()

    return records


def _pathSortKey(path: str) -> tuple[int, ...]:
    """path 文字列をソート用の int タプルに変換する。

    Args:
        path: Materialized Path（例: "1.2.3"）

    Returns:
        ソート用タプル（例: (1, 2, 3)）
    """
    return tuple(int(s) for s in path.split("."))


if __name__ == "__main__":
    # --- 動作確認 ---
    print("=" * 60)
    print("ラウンドトリップテスト: decode → encode → decode")
    print("=" * 60)

    # テストデータ: m_rulebooks のレコード
    testRecords: list[dict] = [
        {"path": "1", "level": 1, "content": "人格ルール", "version": 1},
        {"path": "1.1", "level": 2, "content": "口調", "version": 1},
        {"path": "1.1.1", "level": 3, "content": "基本方針", "version": 1},
        {"path": "1.1.1.1", "level": 4, "content": "生意気なメスガキ口調で話す。\n語尾にハートマークは使わない。", "version": 1},
        {"path": "1.1.2", "level": 3, "content": "禁止事項", "version": 1},
        {"path": "1.1.2.1", "level": 4, "content": "敬語は使わない。", "version": 1},
        {"path": "1.2", "level": 2, "content": "性格", "version": 1},
        {"path": "1.2.1", "level": 3, "content": "コア特性", "version": 1},
        {"path": "1.2.1.1", "level": 4, "content": "煽り気味だが的確に回答する。", "version": 1},
        {"path": "2", "level": 1, "content": "設計哲学", "version": 1},
        {"path": "2.1", "level": 2, "content": "DRY原則", "version": 1},
        {"path": "2.1.1", "level": 3, "content": "定義", "version": 1},
        {"path": "2.1.1.1", "level": 4, "content": "同じロジックを2箇所以上に書かない。", "version": 1},
    ]

    # Step 1: decode（レコード → Markdown）
    md = decode(testRecords)
    print("\n[Step 1] decode結果:")
    print("-" * 40)
    print(md)

    # Step 2: encode（Markdown → レコード）
    encoded = encode(md)
    print("[Step 2] encode結果:")
    print("-" * 40)
    for rec in encoded:
        print(f"  path={rec['path']:<8} level={rec['level']}  content={rec['content'][:40]}")

    # Step 3: 再度 decode（レコード → Markdown）
    md2 = decode(encoded)
    print("\n[Step 3] 再decode結果:")
    print("-" * 40)
    print(md2)

    # 比較
    print("=" * 60)
    if md == md2:
        print("ラウンドトリップ成功: decode→encode→decode の結果が一致")
    else:
        print("ラウンドトリップ失敗: 結果が不一致")
        # 差分表示
        for i, (a, b) in enumerate(zip(md.split("\n"), md2.split("\n"))):
            if a != b:
                print(f"  行{i+1}: '{a}' != '{b}'")

    # --- 追加テスト: Lv3 が本文を持つケース（Lv4 なし） ---
    print("\n" + "=" * 60)
    print("追加テスト: 見出しのみ（本文なし）のケース")
    print("=" * 60)

    testMd = """\
# チーム規約
## コーディング規約
### 変数名は英語
### 関数名はcamelCase
## Git運用
### mainへの直pushは禁止
"""
    encoded2 = encode(testMd)
    print("\nencode結果:")
    for rec in encoded2:
        print(f"  path={rec['path']:<8} level={rec['level']}  content={rec['content'][:40]}")

    md3 = decode(encoded2)
    print("\ndecode結果:")
    print(md3)
