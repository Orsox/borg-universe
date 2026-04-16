-- Phase 3 local task-management schema.

create extension if not exists pgcrypto with schema extensions;

create table if not exists public.projects (
  id text primary key,
  name text not null,
  description text not null default '',
  project_type text not null default 'stm' check (project_type in ('stm', 'nordic', 'python')),
  project_directory text not null default '',
  pycharm_mcp_enabled boolean not null default false,
  pycharm_mcp_sse_url text,
  pycharm_mcp_stream_url text,
  default_platform text,
  default_mcu text,
  default_board text,
  default_topic text,
  active boolean not null default true,
  created_at timestamptz not null default now()
);

alter table public.projects
add column if not exists project_type text not null default 'stm';

alter table public.projects
add column if not exists project_directory text not null default '';

alter table public.projects
add column if not exists pycharm_mcp_enabled boolean not null default false;

alter table public.projects
add column if not exists pycharm_mcp_sse_url text;

alter table public.projects
add column if not exists pycharm_mcp_stream_url text;

alter table public.projects
add column if not exists default_platform text;

alter table public.projects
add column if not exists default_mcu text;

alter table public.projects
add column if not exists default_board text;

alter table public.projects
add column if not exists default_topic text;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'projects_project_type_check'
  ) then
    alter table public.projects
    add constraint projects_project_type_check
    check (project_type in ('stm', 'nordic', 'python'));
  end if;
end
$$;

insert into public.projects (
  id,
  name,
  description,
  project_type,
  project_directory,
  pycharm_mcp_enabled,
  pycharm_mcp_sse_url,
  pycharm_mcp_stream_url,
  default_platform,
  default_mcu,
  default_board,
  default_topic,
  active
)
values
  ('example-1', 'Example 1', 'First example project for the project selector', 'stm', '', false, null, null, 'STM32', null, null, null, true),
  ('example-2', 'Example 2', 'Second example project for the project selector', 'nordic', '', false, null, null, 'Nordic', null, null, null, true),
  (
    'firststart',
    'First Start',
    'Python project prepared for PyCharm MCP controlled runtime actions.',
    'python',
    'D:\Workbench\firststart',
    true,
    'http://127.0.0.1:64769/sse',
    'http://127.0.0.1:64769/stream',
    'Python',
    'CPython',
    'PyCharm',
    'MCP',
    true
  )
on conflict (id) do update
set
  name = excluded.name,
  description = excluded.description,
  project_type = excluded.project_type,
  project_directory = excluded.project_directory,
  pycharm_mcp_enabled = excluded.pycharm_mcp_enabled,
  pycharm_mcp_sse_url = excluded.pycharm_mcp_sse_url,
  pycharm_mcp_stream_url = excluded.pycharm_mcp_stream_url,
  default_platform = excluded.default_platform,
  default_mcu = excluded.default_mcu,
  default_board = excluded.default_board,
  default_topic = excluded.default_topic,
  active = excluded.active;

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
  project_id text,
  workflow_id text,
  status public.task_status not null default 'draft',
  target_platform text,
  target_mcu text,
  board text,
  local_path text,
  pycharm_mcp_enabled boolean not null default false,
  topic text,
  requested_by text,
  assigned_agent text,
  assigned_skill text,
  sequence_index integer not null default 0,
  workspace_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.tasks
add column if not exists sequence_index integer not null default 0;

alter table public.tasks
add column if not exists project_id text;

alter table public.tasks
add column if not exists workflow_id text;

alter table public.tasks
add column if not exists local_path text;

alter table public.tasks
add column if not exists pycharm_mcp_enabled boolean not null default false;

alter table public.tasks
add column if not exists workspace_metadata jsonb not null default '{}'::jsonb;

create table if not exists public.task_events (
  id uuid primary key default extensions.gen_random_uuid(),
  task_id uuid not null references public.tasks(id) on delete cascade,
  event_type text not null,
  message text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.project_specs (
  id uuid primary key default extensions.gen_random_uuid(),
  project_id text not null,
  spec_path text not null,
  spec_type text not null default 'module' check (spec_type in ('project', 'module', 'task', 'handoff')),
  module_name text,
  title text not null default '',
  summary text not null default '',
  content text not null,
  source text not null default 'borg-cube',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (project_id, spec_path)
);

alter table public.project_specs
add column if not exists spec_type text not null default 'module';

alter table public.project_specs
add column if not exists module_name text;

alter table public.project_specs
add column if not exists title text not null default '';

alter table public.project_specs
add column if not exists summary text not null default '';

alter table public.project_specs
add column if not exists source text not null default 'borg-cube';

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

drop trigger if exists project_specs_set_updated_at on public.project_specs;
create trigger project_specs_set_updated_at
before update on public.project_specs
for each row
execute function public.set_updated_at();

create index if not exists idx_tasks_status_sequence_created on public.tasks(status, sequence_index asc, created_at desc);
create index if not exists idx_tasks_workflow_id on public.tasks(workflow_id);
create index if not exists idx_task_events_task_id_created_at on public.task_events(task_id, created_at asc);
create index if not exists idx_project_specs_project_id on public.project_specs(project_id);

alter table public.tasks enable row level security;
alter table public.task_events enable row level security;
alter table public.projects enable row level security;
alter table public.project_specs enable row level security;

drop policy if exists "anon can read projects" on public.projects;
create policy "anon can read projects"
on public.projects for select
to anon
using (true);

drop policy if exists "service role manages projects" on public.projects;
create policy "service role manages projects"
on public.projects for all
to service_role
using (true)
with check (true);

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

drop policy if exists "anon can read project specs" on public.project_specs;
create policy "anon can read project specs"
on public.project_specs for select
to anon
using (true);

drop policy if exists "service role manages project specs" on public.project_specs;
create policy "service role manages project specs"
on public.project_specs for all
to service_role
using (true)
with check (true);

grant select on public.tasks to anon, authenticated;
grant select on public.task_events to anon, authenticated;
grant select on public.projects to anon, authenticated;
grant select on public.project_specs to anon, authenticated;
grant all privileges on public.tasks to service_role;
grant all privileges on public.task_events to service_role;
grant all privileges on public.projects to service_role;
grant all privileges on public.project_specs to service_role;

notify pgrst, 'reload schema';
