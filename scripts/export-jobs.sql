-- Read-only psql snapshot of all job records for one scheduled UTC hour.
-- Supply the tick time through -v tick_at=... (an ISO timestamp). Run on fixtures.
SET TIME ZONE 'UTC';
WITH hour AS (
    SELECT to_char(date_trunc('hour', :'tick_at'::timestamptz),
                   'YYYY-MM-DD"T"HH24:MI:SS"+00:00"') AS scheduled_for
), jobs AS (
    SELECT id, tenant_id, workspace_id, kind, parent_id, name,
           data, status, idempotency_key, created_at
    FROM public.records, hour
    WHERE CASE WHEN kind = 'job'
          THEN data::json->>'scheduled_for' = hour.scheduled_for
          ELSE false END
)
SELECT coalesce(json_agg(jobs ORDER BY tenant_id, workspace_id, idempotency_key, id), '[]'::json)
FROM jobs;
