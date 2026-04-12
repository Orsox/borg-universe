-- Phase 7 artifact persistence for agentic processing.

create table if not exists public.artifacts (
  id uuid primary key default extensions.gen_random_uuid(),
  task_id uuid not null references public.tasks(id) on delete cascade,
  artifact_type text not null,
  path_or_storage_key text not null,
  checksum text,
  created_at timestamptz not null default now()
);

create index if not exists idx_artifacts_task_id_created_at on public.artifacts(task_id, created_at desc);

alter table public.artifacts enable row level security;

drop policy if exists "anon can read artifacts" on public.artifacts;
create policy "anon can read artifacts"
on public.artifacts for select
to anon
using (true);

drop policy if exists "service role manages artifacts" on public.artifacts;
create policy "service role manages artifacts"
on public.artifacts for all
to service_role
using (true)
with check (true);

grant select on public.artifacts to anon, authenticated;
grant all privileges on public.artifacts to service_role;

notify pgrst, 'reload schema';
