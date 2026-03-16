-- cre_viw_v_active_rulebooks.sql
-- v_active_rulebooks ビュー定義

CREATE VIEW v_active_rulebooks AS
SELECT r.*
FROM t_rulebooks r
INNER JOIN (
    SELECT key, MAX(version) AS max_version
    FROM t_rulebooks
    GROUP BY key
) latest ON r.key = latest.key AND r.version = latest.max_version
WHERE r.is_retired = FALSE;
