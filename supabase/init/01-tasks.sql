-- Phase 3 local task-management schema.

create extension if not exists pgcrypto with schema extensions;

do $$
begin
  if not exists (select 1 from pg_type where typname = 'task_status') then
    create type public.task_status as enum (
      'draft',
      'queued',
      'running',
      'needs_input',
      'review_required',
      'done',
      'failed',
      'cancelled'
    );
  end if;
end
$$;

create table if not exists public.tasks (
  id uuid primary key default extensions.gen_random_uuid(),
  title text not null,
  description text not null default '',
  status public.task_status not null default 'draft',
  target_platform text,
  target_mcu text,
  board text,
  topic text,
  requested_by text,
  assigned_agent text,
  assigned_skill text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.task_events (
  id uuid primary key default extensions.gen_random_uuid(),
  task_id uuid not null references public.tasks(id) on delete cascade,
  event_type text not null,
  message text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists tasks_set_updated_at on public.tasks;
create trigger tasks_set_updated_at
before update on public.tasks
for each row
execute function public.set_updated_at();

create index if not exists idx_tasks_status_created_at on public.tasks(status, created_at desc);
create index if not exists idx_task_events_task_id_created_at on public.task_events(task_id, created_at asc);

alter table public.tasks enable row level security;
alter table public.task_events enable row level security;

drop policy if exists "anon can read tasks" on public.tasks;
create policy "anon can read tasks"
on public.tasks for select
to anon
using (true);

drop policy if exists "service role manages tasks" on public.tasks;
create policy "service role manages tasks"
on public.tasks for all
to service_role
using (true)
with check (true);

drop policy if exists "anon can read task events" on public.task_events;
create policy "anon can read task events"
on public.task_events for select
to anon
using (true);

drop policy if exists "service role manages task events" on public.task_events;
create policy "service role manages task events"
on public.task_events for all
to service_role
using (true)
with check (true);

grant select on public.tasks to anon, authenticated;
grant select on public.task_events to anon, authenticated;
grant all privileges on public.tasks to service_role;
grant all privileges on public.task_events to service_role;

notify pgrst, 'reload schema';
