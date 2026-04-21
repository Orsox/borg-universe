-- Phase 7 Project-Registry binding schema.

create table if not exists public.project_registry_bindings (
  id uuid primary key default extensions.gen_random_uuid(),
  project_id text not null references public.projects(id) on delete cascade,
  unit_name text not null,
  unit_type text not null check (unit_type in ('agent', 'skill')),
  created_at timestamptz not null default now(),
  unique(project_id, unit_name, unit_type)
);

create index if not exists idx_project_registry_bindings_project_id on public.project_registry_bindings(project_id);

alter table public.project_registry_bindings enable row level security;

drop policy if exists "anon can read project_registry_bindings" on public.project_registry_bindings;
create policy "anon can read project_registry_bindings"
on public.project_registry_bindings for select
to anon
using (true);

drop policy if exists "service role manages project_registry_bindings" on public.project_registry_bindings;
create policy "service role manages project_registry_bindings"
on public.project_registry_bindings for all
to service_role
using (true)
with check (true);

grant select on public.project_registry_bindings to anon, authenticated;
grant all privileges on public.project_registry_bindings to service_role;

notify pgrst, 'reload schema';
