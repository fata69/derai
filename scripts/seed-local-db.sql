-- Run as the local fixture database owner; idempotent, preserves existing jobs.
INSERT INTO public.records (
    id, tenant_id, workspace_id, kind, parent_id,
    name, data, status, idempotency_key, created_at
) VALUES (
    '11111111-1111-4111-8111-111111111111',
    '22222222-2222-4222-8222-222222222222',
    '33333333-3333-4333-8333-333333333333',
    'topic', NULL, 'Contoh PRD',
    '{"keywords":[" TNI ","Indonesia","tni",""]}',
    'ready', NULL, '2026-11-13T04:00:00+00:00'
) ON CONFLICT (id) DO NOTHING;
