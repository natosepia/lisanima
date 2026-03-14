# スキーママイグレーション戦略

## 1. 概要

lisanimaのDBスキーマを安全に変更するための戦略・運用ルール・ポリシーを定義する。

- **対象**: DDLスキーマの変更（テーブル追加・カラム変更・制約変更など）
- **非対象**: データ移行（Markdown→DB等）は [90_markdown_migration.md](90_markdown_migration.md) を参照
- **DDLのSSOT**: [04_schema.md](04_schema.md) セクション7が「現在のあるべきDDL」。本ドキュメントはそれを「どう安全に適用するか」の戦略を定義する

## 2. 基本方針: DROP & CREATE

ALTERによる差分適用を廃止し、常に**理想形DDLでDROP & CREATE**する。

| 項目 | 方針 |
|------|------|
| ALTER TABLE | 使用しない |
| スキーマ変更 | 04_schema.md のDDLを理想形として編集し、丸ごと再作成する |
| データ保全 | 元テーブルを `_work` サフィックスで退避してからCREATE |
| IDENTITY値 | 退避データから引き継ぐ（後述） |

**採用理由:**

- ALTERの積み重ねはDDLの実態と設計書の乖離を生む
- 「今のあるべき姿」を04_schema.mdに一元管理し、それをそのまま適用する方が整合性を維持しやすい
- 個人開発規模ではサービス停止による一括適用が現実的

## 3. マイグレーション手順

### 3.1 前提条件

- **サービス停止必須**: `systemctl stop lisanima.service` を実行してから作業する
- **バックアップ**: `pg_dump lisanima_db > backup_YYYYMMDD.sql` で事前にバックアップを取得する

### 3.2 実行フロー

```
1. サービス停止
2. pg_dump バックアップ
3. _work テーブルへの退避（ユーティリティプロシージャ）
4. 既存テーブル DROP（FK依存の逆順）
5. 新DDL CREATE（FK依存の順序）
6. _work → 新テーブルへデータ移行
7. IDENTITY値の引き継ぎ
8. 動作確認
9. サービス再開
10. _work テーブルの手動削除（なとせが確認後に実施）
```

### 3.3 _work テーブルの退避

元テーブルを `{テーブル名}_work` にリネームすることでデータを保全する。

```sql
-- 例: t_messages → t_messages_work
ALTER TABLE t_messages RENAME TO t_messages_work;
```

退避後、新DDLでCREATEした空テーブルに対してデータを移行する。

### 3.4 IDENTITY値の引き継ぎ

`GENERATED ALWAYS AS IDENTITY` のシーケンスは、退避データの最大値に合わせてリセットする。

```sql
-- 例: t_messages の IDENTITY 値を引き継ぐ
SELECT setval(
    pg_get_serial_sequence('t_messages', 'id'),
    (SELECT COALESCE(MAX(id), 0) FROM t_messages_work)
);

-- OVERRIDING SYSTEM VALUE でIDENTITY列に明示的な値を挿入
INSERT INTO t_messages (id, session_id, speaker, content, ...)
OVERRIDING SYSTEM VALUE
SELECT id, session_id, speaker, content, ...
FROM t_messages_work;
```

## 4. FK依存とテーブル操作順序

### 4.1 DROP順序（FK依存の逆順）

FK参照先が残っている状態で参照元をDROPする。つまり**子テーブルから先にDROP**する。

```
子テーブル（FK参照元）→ 親テーブル（FK参照先）の順
```

### 4.2 CREATE順序（FK依存の順）

FK参照先を先にCREATEする。つまり**親テーブルから先にCREATE**する。

```
親テーブル（FK参照先）→ 子テーブル（FK参照元）の順
```

### 4.3 依存順序の導出

`pg_constraint` からトポロジカルソートで機械的に導出する。ユーティリティプロシージャ内で自動判定するため、手動での順序管理は不要。

```sql
-- FK依存関係の確認クエリ（参考）
SELECT
    tc.table_name AS child_table,
    ccu.table_name AS parent_table
FROM information_schema.table_constraints tc
JOIN information_schema.constraint_column_usage ccu
    ON tc.constraint_name = ccu.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_schema = 'public';
```

## 5. ユーティリティプロシージャ

マイグレーションの退避・DROP・CREATE・データ移行を自動化するユーティリティプロシージャを `migrations/` ディレクトリに配置する。

プロシージャの実装は `migrations/` 配下のSQLファイルを参照のこと。

### 責務

| 処理 | 内容 |
|------|------|
| 退避 | 対象テーブルを `_work` にリネーム |
| DROP順序の決定 | pg_constraint からFK依存を解析し、子→親の順でDROP |
| CREATE | 04_schema.md セクション7のDDLをそのまま実行 |
| データ移行 | `_work` → 新テーブルへINSERT（カラム差異はプロシージャ内で吸収） |
| IDENTITY引き継ぎ | 各テーブルのシーケンスを `_work` のMAX(id)にリセット |

## 6. スコープと制約

### 6.1 対応範囲

- カラムの追加・削除・型変更
- 制約の追加・変更・削除
- テーブルの追加・削除
- インデックスの追加・削除

### 6.2 スコープ外（ハイブリッド戦術）

以下のケースは汎用プロシージャだけでは対応できないため、**手動SQLとの併用**で対応する。

- テーブル分割・統合（例: 1テーブルを2テーブルに分離）
- カラム値の変換を伴う移行（例: INTEGER → JSONB への型変換+データ変換）
- 複数テーブル間のデータ再配置

これらは個別のマイグレーションSQLを手書きし、プロシージャと組み合わせて実行する。

## 7. _work テーブルの管理

| 項目 | ルール |
|------|--------|
| 命名 | `{元テーブル名}_work` |
| 作成 | ユーティリティプロシージャが自動でリネーム |
| 削除 | **なとせが手動で確認後に削除** |
| 保持期間 | なとせの判断に委ねる（動作確認が完了するまで保持） |

_work テーブルはロールバック用のセーフティネットとして機能する。万一データ移行に問題があった場合、_work テーブルからの復旧が可能。

## 8. migrations/ ディレクトリ

### 8.1 構成

```
migrations/
├── 002_oauth.sql          # OAuth 2.1テーブル追加（適用済み）
├── xxx_migration_utils.sql # マイグレーションユーティリティプロシージャ（予定）
└── ...
```

### 8.2 ファイル命名規則

| 形式 | 用途 |
|------|------|
| `NNN_{内容}.sql` | 連番で管理。NNN は 001 から昇順 |

### 8.3 運用ルール

- 各SQLファイルは**冪等性を意識**する（`IF NOT EXISTS`, `ON CONFLICT DO NOTHING` 等）
- 適用済みのマイグレーションファイルは削除せず履歴として保持する
- 04_schema.md のDDLが常にSSOT。migrations/ のSQLは「そこに至るまでの差分記録」

## 9. 既存マイグレーションとの関係

002_oauth.sql は ALTER 方式で作成された過渡的なマイグレーション。DROP & CREATE 方式への移行後は、04_schema.md のDDLが唯一の正とし、002_oauth.sql は適用済み履歴として保持する。

今後のスキーマ変更では ALTER は使用せず、本ドキュメントの手順に従う。
