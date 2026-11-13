-- psql-only, idempotent. Run inside this project's local Compose db service.
-- The separate *_test database is disposable; the seeded demo DB is preserved.
SELECT 'CREATE DATABASE derai_scheduler_test OWNER derai_local_admin'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'derai_scheduler_test')
\gexec
