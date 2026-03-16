-- ============================================================
-- cre_proc_migration_evacuate.sql
-- 旧テーブルを _work にリネームして退避するプロシージャ
-- ============================================================
--
-- 概要:
--   DROP & CREATE方式によるスキーマ変更の第1段階。
--   旧テーブルを {old_name}_work にリネームして退避する。
--   VIEWの依存を検出し先に DROP VIEW する（NOTICE出力）。
--   migration_get_drop_order() で安全なDROP順を決定する。
--   存在しないテーブルはNOTICEでスキップ（冪等性）。
--
-- 引数:
--   table_mapping JSONB
--     旧テーブル名→新テーブル名のマッピング。
--     書式: {"old_name": "new_name", "obsolete_table": null}
--     - value が文字列 → 新テーブル名（evacuate後にtransferで移行）
--     - value が null   → 廃止テーブル（退避のみ、transferではスキップ）
--     例: {"sessions": "t_sessions", "messages": "t_messages", "m_category": null}
--
-- 依存関係:
--   migration_get_drop_order() を内部で呼び出す。
--   先に cre_func_migration_get_drop_order.sql を実行しておくこと。
--
-- マイグレーション実行フロー:
--   1. サービス停止（systemctl stop lisanima）
--   2. pg_dump バックアップ
--   3. BEGIN;
--   4. CALL migration_evacuate('{"old": "new", ...}'::jsonb);   ← 本プロシージャ
--   5. 新DDL実行（CREATE TABLE ... / CREATE VIEW ... / CREATE INDEX ...）
--   6. CALL migration_transfer('{"old": "new", ...}'::jsonb, ...);
--   7. COMMIT;
--   8. 動作確認後、_work テーブルを手動で削除
--
-- 制約・前提条件:
--   - BEGIN/COMMITはプロシージャ内部に含まない（呼び出し側で制御）
--   - 対象テーブルは public スキーマに限定
--   - _work テーブルの削除は運用者（なとせ）が手動で行う
-- ============================================================

CREATE OR REPLACE PROCEDURE migration_evacuate(table_mapping JSONB)
LANGUAGE plpgsql
AS $$
DECLARE
    old_name     TEXT;
    target_tables TEXT[];
    drop_order   TEXT[];
    tbl          TEXT;
    view_name    TEXT;
    view_dropped BOOLEAN;
BEGIN
    -- table_mappingのキー（旧テーブル名）を配列に収集
    target_tables := ARRAY(SELECT jsonb_object_keys(table_mapping));

    IF array_length(target_tables, 1) IS NULL THEN
        RAISE NOTICE 'migration_evacuate: table_mappingが空です。何もしません。';
        RETURN;
    END IF;

    -- DROP安全順を取得（子→親）
    drop_order := migration_get_drop_order(target_tables);

    RAISE NOTICE 'migration_evacuate: DROP順 = %', drop_order;

    -- DROP順に処理
    FOREACH tbl IN ARRAY drop_order LOOP
        -- テーブル存在確認
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = tbl
              AND table_type = 'BASE TABLE'
        ) THEN
            RAISE NOTICE 'migration_evacuate: テーブル "%" は存在しません。スキップします。', tbl;
            CONTINUE;
        END IF;

        -- VIEW依存の検出とDROP
        -- pg_depend + pg_rewrite でこのテーブルに依存するVIEWを検出
        view_dropped := FALSE;
        FOR view_name IN
            SELECT DISTINCT v.relname::text
            FROM pg_depend d
            JOIN pg_rewrite rw ON rw.oid = d.objid
            JOIN pg_class v ON v.oid = rw.ev_class
            JOIN pg_class t ON t.oid = d.refobjid
            JOIN pg_namespace vn ON vn.oid = v.relnamespace
            WHERE t.relname = tbl
              AND v.relkind = 'v'       -- VIEW
              AND t.relkind = 'r'       -- テーブル
              AND vn.nspname = 'public'
              AND d.deptype = 'n'       -- 通常依存
              AND d.classid = 'pg_rewrite'::regclass
        LOOP
            RAISE NOTICE 'migration_evacuate: VIEW "%" を DROP します（テーブル "%" に依存）。', view_name, tbl;
            EXECUTE format('DROP VIEW IF EXISTS %I CASCADE', view_name);
            view_dropped := TRUE;
        END LOOP;

        -- _work が既に存在する場合のチェック
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = tbl || '_work'
        ) THEN
            RAISE EXCEPTION 'migration_evacuate: "%" が既に存在します。前回のマイグレーションの残骸を確認してください。',
                tbl || '_work';
        END IF;

        -- リネーム実行
        RAISE NOTICE 'migration_evacuate: "%" → "%_work" にリネームします。', tbl, tbl;
        EXECUTE format('ALTER TABLE %I RENAME TO %I', tbl, tbl || '_work');
    END LOOP;

    RAISE NOTICE 'migration_evacuate: 完了。';
END;
$$;
