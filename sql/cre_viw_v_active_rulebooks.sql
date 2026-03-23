-- cre_viw_v_active_rulebooks.sql
-- v_active_rulebooks ビュー定義（m_rulebooks 参照）

CREATE OR REPLACE VIEW v_active_rulebooks AS
SELECT r.*
FROM m_rulebooks r
INNER JOIN (
    SELECT path, MAX(version) AS max_version
    FROM m_rulebooks
    GROUP BY path
) latest ON r.path = latest.path
    AND r.version = latest.max_version
WHERE r.is_retired = FALSE;
