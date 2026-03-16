-- ============================================================
-- cre_func_migration_get_drop_order.sql
-- FK依存グラフからDROP安全順を導出するヘルパー関数
-- ============================================================
--
-- 概要:
--   対象テーブル群のFK依存関係を解析し、DROP安全順（子→親）を返す。
--   カーンのアルゴリズム（入次数ベースのトポロジカルソート）で親→子を求め、
--   逆順にすることでDROP順を導出する。
--   循環参照を検出した場合は RAISE EXCEPTION で中断する。
--
-- 引数:
--   target_tables TEXT[]
--     DROP順を求めたいテーブル名の配列。
--     target_tablesに含まれないテーブルへのFK依存は無視する。
--
-- 戻り値:
--   TEXT[] — DROP安全順（子→親）のテーブル名配列
--
-- 依存関係:
--   なし（他のプロシージャから呼ばれるヘルパー関数）
--
-- 実行フローにおける位置づけ:
--   migration_evacuate / migration_transfer の内部で呼ばれる。
--   単体で直接呼ぶ必要はない。
--
--   マイグレーション全体フロー:
--     1. サービス停止（systemctl stop lisanima）
--     2. pg_dump バックアップ
--     3. BEGIN;
--     4. CALL migration_evacuate('{"old": "new", ...}'::jsonb);
--     5. 新DDL実行（CREATE TABLE ... / CREATE VIEW ... / CREATE INDEX ...）
--     6. CALL migration_transfer('{"old": "new", ...}'::jsonb, ...);
--     7. COMMIT;
--     8. 動作確認後、_work テーブルを手動で削除
--
-- 制約・前提条件:
--   - 対象テーブルは public スキーマに限定
--   - 循環FK参照があるスキーマには対応しない（EXCEPTION送出）
-- ============================================================

CREATE OR REPLACE FUNCTION migration_get_drop_order(target_tables TEXT[])
RETURNS TEXT[]
LANGUAGE plpgsql
AS $$
DECLARE
    -- 入次数（そのテーブルを参照している他テーブルの数）
    in_degree   JSONB := '{}'::jsonb;
    -- 隣接リスト: parent -> children[]
    adj_list    JSONB := '{}'::jsonb;
    -- 処理用
    tbl         TEXT;
    parent_tbl  TEXT;
    child_tbl   TEXT;
    queue       TEXT[];
    sorted      TEXT[];  -- 親→子の順（トポロジカル順）
    result      TEXT[];  -- 子→親の順（DROP順）
    deg         INT;
    children    JSONB;
    i           INT;
    child_text  TEXT;
BEGIN
    -- 全対象テーブルの入次数を0で初期化
    FOREACH tbl IN ARRAY target_tables LOOP
        in_degree := in_degree || jsonb_build_object(tbl, 0);
        adj_list  := adj_list  || jsonb_build_object(tbl, '[]'::jsonb);
    END LOOP;

    -- FK依存グラフ構築: 対象テーブル間のFK制約のみ対象
    -- contype='f' は外部キー制約
    -- parent（参照先）→ child（参照元）の辺を張る
    FOR parent_tbl, child_tbl IN
        SELECT
            p.relname::text AS parent_name,
            c.relname::text AS child_name
        FROM pg_constraint con
        JOIN pg_class c ON c.oid = con.conrelid      -- 制約を持つテーブル（子）
        JOIN pg_class p ON p.oid = con.confrelid      -- 参照先テーブル（親）
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE con.contype = 'f'
          AND n.nspname = 'public'
          AND c.relname = ANY(target_tables)
          AND p.relname = ANY(target_tables)
          AND c.relname <> p.relname  -- 自己参照は無視
    LOOP
        -- 入次数を加算（childがparentに依存）
        deg := (in_degree->>child_tbl)::int + 1;
        in_degree := jsonb_set(in_degree, ARRAY[child_tbl], to_jsonb(deg));

        -- 隣接リスト: parentの子リストにchildを追加
        children := adj_list->parent_tbl;
        -- 重複チェック
        IF NOT children @> to_jsonb(child_tbl) THEN
            children := children || to_jsonb(child_tbl);
            adj_list := jsonb_set(adj_list, ARRAY[parent_tbl], children);
        END IF;
    END LOOP;

    -- カーンのアルゴリズム: 入次数0のノードからスタート
    queue := ARRAY[]::text[];
    FOREACH tbl IN ARRAY target_tables LOOP
        IF (in_degree->>tbl)::int = 0 THEN
            queue := array_append(queue, tbl);
        END IF;
    END LOOP;

    sorted := ARRAY[]::text[];

    WHILE array_length(queue, 1) IS NOT NULL AND array_length(queue, 1) > 0 LOOP
        -- キューの先頭を取り出す
        tbl := queue[1];
        queue := queue[2:];
        sorted := array_append(sorted, tbl);

        -- tblの子ノードの入次数を減らす
        children := adj_list->tbl;
        IF children IS NOT NULL AND jsonb_array_length(children) > 0 THEN
            FOR i IN 0..jsonb_array_length(children) - 1 LOOP
                child_text := children->>i;
                deg := (in_degree->>child_text)::int - 1;
                in_degree := jsonb_set(in_degree, ARRAY[child_text], to_jsonb(deg));
                IF deg = 0 THEN
                    queue := array_append(queue, child_text);
                END IF;
            END LOOP;
        END IF;
    END LOOP;

    -- 循環参照検出
    IF array_length(sorted, 1) IS DISTINCT FROM array_length(target_tables, 1) THEN
        RAISE EXCEPTION 'migration_get_drop_order: 循環参照を検出しました。sorted=%, target=%',
            sorted, target_tables;
    END IF;

    -- 逆順にしてDROP順（子→親）を返す
    result := ARRAY[]::text[];
    FOR i IN REVERSE array_length(sorted, 1)..1 LOOP
        result := array_append(result, sorted[i]);
    END LOOP;

    RETURN result;
END;
$$;
