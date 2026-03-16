-- ============================================================
-- cre_proc_migration_transfer.sql
-- _work テーブルから新テーブルへデータを移行するプロシージャ
-- ============================================================
--
-- 概要:
--   DROP & CREATE方式によるスキーマ変更の第3段階。
--   _work テーブルから新テーブルへデータを移行し、IDENTITYシーケンスを引き継ぐ。
--   同名カラムを自動マッピングし、Generated Columnは除外する。
--   custom_mappingsでカラム→SQL式の上書きが可能。
--   親→子の順でINSERT（FK参照先が先）。
--
-- 引数:
--   table_mapping JSONB
--     旧テーブル名→新テーブル名のマッピング。
--     書式: {"old_name": "new_name", "obsolete_table": null}
--     - value が文字列 → 新テーブル名（transferで移行）
--     - value が null   → 廃止テーブル（スキップ）
--     例: {"sessions": "t_sessions", "messages": "t_messages", "m_category": null}
--
--   custom_mappings JSONB (DEFAULT NULL)
--     テーブルごとのカラム→SQL式マッピング。NULLなら全カラム自動マッピング。
--     書式: {"new_table_name": {"new_col": "SQL式"}}
--     SQL式中では _work テーブルのカラムを参照可能。
--     custom_mappingsで指定されたカラムは自動マッピングから除外される。
--     例: {"t_messages": {"joy": "((emotion >> 24) & 255)::smallint"}}
--
-- 依存関係:
--   migration_get_drop_order() を内部で呼び出す。
--   先に cre_func_migration_get_drop_order.sql を実行しておくこと。
--   evacuate → 新DDL実行 → transfer の順序を守ること。
--
-- マイグレーション実行フロー:
--   1. サービス停止（systemctl stop lisanima）
--   2. pg_dump バックアップ
--   3. BEGIN;
--   4. CALL migration_evacuate('{"old": "new", ...}'::jsonb);
--   5. 新DDL実行（CREATE TABLE ... / CREATE VIEW ... / CREATE INDEX ...）
--   6. CALL migration_transfer('{"old": "new", ...}'::jsonb, ...);  ← 本プロシージャ
--   7. COMMIT;
--   8. 動作確認後、_work テーブルを手動で削除
--
-- 制約・前提条件:
--   - BEGIN/COMMITはプロシージャ内部に含まない（呼び出し側で制御）
--   - evacuate → 新DDL実行 → transfer の順序を守ること
--   - 対象テーブルは public スキーマに限定
-- ============================================================

CREATE OR REPLACE PROCEDURE migration_transfer(
    table_mapping   JSONB,
    custom_mappings JSONB DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
DECLARE
    old_name       TEXT;
    new_name       TEXT;
    work_name      TEXT;
    new_tables     TEXT[];
    insert_order   TEXT[];
    tbl            TEXT;
    -- カラムマッピング用
    work_cols      TEXT[];
    new_cols       TEXT[];
    gen_cols       TEXT[];
    common_cols    TEXT[];
    custom_cols    TEXT[];
    select_exprs   TEXT[];
    insert_cols    TEXT[];
    col            TEXT;
    expr           TEXT;
    custom_map     JSONB;
    -- シーケンス用
    seq_name       TEXT;
    max_val        BIGINT;
    -- 逆引き: new_name → old_name
    reverse_map    JSONB := '{}'::jsonb;
    -- 行数カウント
    row_count      BIGINT;
BEGIN
    -- null値（廃止テーブル）を除外して、新テーブル名の配列を構築
    -- 同時に逆引きマップ（new_name→old_name）も構築
    new_tables := ARRAY[]::text[];
    FOR old_name, new_name IN
        SELECT key, value#>>'{}'
        FROM jsonb_each(table_mapping)
        WHERE value IS NOT NULL
          AND jsonb_typeof(value) = 'string'
    LOOP
        new_tables := array_append(new_tables, new_name);
        reverse_map := reverse_map || jsonb_build_object(new_name, old_name);
    END LOOP;

    IF array_length(new_tables, 1) IS NULL THEN
        RAISE NOTICE 'migration_transfer: 移行対象テーブルがありません。';
        RETURN;
    END IF;

    -- INSERT順を取得: drop_orderの逆順（親→子）
    -- migration_get_drop_orderは子→親を返すので、逆順にすれば親→子
    insert_order := ARRAY[]::text[];
    DECLARE
        drop_ord TEXT[];
        i        INT;
    BEGIN
        drop_ord := migration_get_drop_order(new_tables);
        FOR i IN REVERSE array_length(drop_ord, 1)..1 LOOP
            insert_order := array_append(insert_order, drop_ord[i]);
        END LOOP;
    END;

    RAISE NOTICE 'migration_transfer: INSERT順 = %', insert_order;

    -- INSERT順にデータ移行
    FOREACH tbl IN ARRAY insert_order LOOP
        old_name  := reverse_map->>tbl;
        new_name  := tbl;
        work_name := old_name || '_work';

        RAISE NOTICE 'migration_transfer: "%" → "%" を処理中...', work_name, new_name;

        -- _work テーブル存在確認
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = work_name
              AND table_type = 'BASE TABLE'
        ) THEN
            RAISE EXCEPTION 'migration_transfer: _workテーブル "%" が存在しません。evacuateを先に実行してください。',
                work_name;
        END IF;

        -- 新テーブル存在確認
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = new_name
              AND table_type = 'BASE TABLE'
        ) THEN
            RAISE EXCEPTION 'migration_transfer: 新テーブル "%" が存在しません。DDLを先に実行してください。',
                new_name;
        END IF;

        -- _work テーブルのカラム一覧取得
        work_cols := ARRAY(
            SELECT column_name::text
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = work_name
            ORDER BY ordinal_position
        );

        -- 新テーブルのカラム一覧取得（Generated Columnを除外）
        new_cols := ARRAY(
            SELECT column_name::text
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = new_name
              AND generation_expression IS NULL
            ORDER BY ordinal_position
        );

        -- 新テーブルのGenerated Column一覧（ログ用）
        gen_cols := ARRAY(
            SELECT column_name::text
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = new_name
              AND generation_expression IS NOT NULL
        );

        IF array_length(gen_cols, 1) IS NOT NULL THEN
            RAISE NOTICE 'migration_transfer: "%"のGenerated Columns（除外）: %', new_name, gen_cols;
        END IF;

        -- custom_mappingsの取得
        custom_map := NULL;
        custom_cols := ARRAY[]::text[];
        IF custom_mappings IS NOT NULL AND custom_mappings ? new_name THEN
            custom_map := custom_mappings->new_name;
            custom_cols := ARRAY(SELECT jsonb_object_keys(custom_map));
            RAISE NOTICE 'migration_transfer: "%"のcustom_mappings: %', new_name, custom_cols;
        END IF;

        -- 同名カラムの積集合（custom_mappingsのカラムを除外）
        common_cols := ARRAY(
            SELECT unnest(work_cols)
            INTERSECT
            SELECT unnest(new_cols)
            EXCEPT
            SELECT unnest(custom_cols)
            ORDER BY 1
        );

        -- SELECT式とINSERT先カラムを構築
        select_exprs := ARRAY[]::text[];
        insert_cols  := ARRAY[]::text[];

        -- 自動マッピング分
        FOREACH col IN ARRAY common_cols LOOP
            insert_cols  := array_append(insert_cols, format('%I', col));
            select_exprs := array_append(select_exprs, format('%I', col));
        END LOOP;

        -- custom_mappings分
        IF array_length(custom_cols, 1) IS NOT NULL THEN
            FOREACH col IN ARRAY custom_cols LOOP
                -- custom_colが新テーブルに存在するか確認
                IF col = ANY(new_cols) THEN
                    expr := custom_map->>col;
                    insert_cols  := array_append(insert_cols, format('%I', col));
                    select_exprs := array_append(select_exprs, expr);
                ELSE
                    RAISE NOTICE 'migration_transfer: custom_mappingsのカラム "%"は新テーブル "%"に存在しません。スキップします。',
                        col, new_name;
                END IF;
            END LOOP;
        END IF;

        -- INSERTカラムがない場合（ありえないが安全弁）
        IF array_length(insert_cols, 1) IS NULL THEN
            RAISE NOTICE 'migration_transfer: "%"に移行対象カラムがありません。スキップします。', new_name;
            CONTINUE;
        END IF;

        -- INSERT実行（OVERRIDING SYSTEM VALUE でIDENTITY上書き）
        EXECUTE format(
            'INSERT INTO %I (%s) OVERRIDING SYSTEM VALUE SELECT %s FROM %I',
            new_name,
            array_to_string(insert_cols, ', '),
            array_to_string(select_exprs, ', '),
            work_name
        );

        GET DIAGNOSTICS row_count = ROW_COUNT;
        RAISE NOTICE 'migration_transfer: "%" → "%": %行を移行しました。', work_name, new_name, row_count;

        -- IDENTITYシーケンスの引き継ぎ
        -- 新テーブルの各カラムについてシーケンスを検出
        FOREACH col IN ARRAY new_cols LOOP
            seq_name := pg_get_serial_sequence('public.' || new_name, col);
            IF seq_name IS NOT NULL THEN
                EXECUTE format('SELECT MAX(%I) FROM %I', col, new_name) INTO max_val;
                IF max_val IS NOT NULL THEN
                    PERFORM setval(seq_name, max_val);
                    RAISE NOTICE 'migration_transfer: シーケンス "%"を%に設定しました。', seq_name, max_val;
                ELSE
                    -- データなしの場合: 次のnextvalが1を返すように設定
                    PERFORM setval(seq_name, 1, false);
                    RAISE NOTICE 'migration_transfer: シーケンス "%"を初期値(1)に設定しました（データなし）。', seq_name;
                END IF;
            END IF;
        END LOOP;

    END LOOP;

    RAISE NOTICE 'migration_transfer: 完了。';
END;
$$;
