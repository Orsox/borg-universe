-- Issues table for tracking project issues.

create table if not exists public.issues (
  id text primary key default extensions.gen_random_uuid()::text,
  project_id text references public.projects(id) on delete set null,
  title text not null,
  description text not null default '',
  status text not null default 'open'
    check (status in ('open', 'in_progress', 'resolved', 'closed')),
  priority text not null default 'medium'
    check (priority in ('low', 'medium', 'high', 'critical')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- RLS --
alter table public.issues enable row level security;

drop policy if exists "issues_select" on public.issues;
create policy "issues_select" on public.issues
  for select using (true);

drop policy if exists "issues_insert" on public.issues;
create policy "issues_insert" on public.issues
  for insert with check (true);

drop policy if exists "issues_update" on public.issues;
create policy "issues_update" on public.issues
  for update using (true) with check (true);

drop policy if exists "issues_delete" on public.issues;
create policy "issues_delete" on public.issues
  for delete using (true);

-- Grants --
grant select on public.issues to anon, authenticated;
grant all privileges on public.issues to service_role;

notify pgrst, 'reload schema';
