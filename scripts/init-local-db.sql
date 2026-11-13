-- DEVELOPMENT FIXTURE ONLY: automatically applied to a NEW local Compose volume.
-- Do not apply this schema or these broad scope policies to the live DERAI DB.
CREATE ROLE derai_worker LOGIN PASSWORD 'derai_local_worker';

CREATE TABLE public.records (
    id varchar(36) PRIMARY KEY,
    tenant_id varchar(36) NOT NULL,
    workspace_id varchar(36) NOT NULL,
    kind varchar(40) NOT NULL,
    parent_id varchar(36),
    name varchar(300),
    data text NOT NULL,
    status varchar(30) NOT NULL,
    idempotency_key varchar(200),
    created_at varchar(40) NOT NULL,
    CONSTRAINT uq_scope_kind_idem
        UNIQUE (tenant_id, workspace_id, kind, idempotency_key)
);

GRANT USAGE ON SCHEMA public TO derai_worker;
GRANT SELECT, INSERT ON public.records TO derai_worker;
ALTER TABLE public.records ENABLE ROW LEVEL SECURITY;
CREATE POLICY worker_read_fixture ON public.records
    FOR SELECT TO derai_worker USING (true);
CREATE POLICY worker_insert_fixture ON public.records
    FOR INSERT TO derai_worker
    WITH CHECK (kind = 'job' AND status = 'queued');
