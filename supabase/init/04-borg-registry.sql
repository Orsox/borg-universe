-- Phase 6 Borg agent/skill registry schema.

create table if not exists public.agents (
  id uuid primary key default extensions.gen_random_uuid(),
  name text not null unique,
  description text not null default '',
  path text not null,
  enabled boolean not null default true,
  version text,
  maintainer text,
  requires_supabase_project_lookup boolean not null default true,
  allowed_supabase_scopes text[] not null default array['project_context', 'knowledge', 'rules', 'examples'],
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.skills (
  id uuid primary key default extensions.gen_random_uuid(),
  name text not null unique,
  description text not null default '',
  path text not null,
  enabled boolean not null default true,
  version text,
  input_schema jsonb not null default '{}'::jsonb,
  output_schema jsonb not null default '{}'::jsonb,
  requires_supabase_project_lookup boolean not null default true,
  allowed_supabase_scopes text[] not null default array['project_context', 'knowledge', 'rules', 'examples'],
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists agents_set_updated_at on public.agents;
create trigger agents_set_updated_at
before update on public.agents
for each row
execute function public.set_updated_at();

drop trigger if exists skills_set_updated_at on public.skills;
create trigger skills_set_updated_at
before update on public.skills
for each row
execute function public.set_updated_at();

create index if not exists idx_agents_enabled on public.agents(enabled);
create index if not exists idx_skills_enabled on public.skills(enabled);

alter table public.agents enable row level security;
alter table public.skills enable row level security;

drop policy if exists "anon can read agents" on public.agents;
create policy "anon can read agents"
on public.agents for select
to anon
using (true);

drop policy if exists "service role manages agents" on public.agents;
create policy "service role manages agents"
on public.agents for all
to service_role
using (true)
with check (true);

drop policy if exists "anon can read skills" on public.skills;
create policy "anon can read skills"
on public.skills for select
to anon
using (true);

drop policy if exists "service role manages skills" on public.skills;
create policy "service role manages skills"
on public.skills for all
to service_role
using (true)
with check (true);

grant select on public.agents to anon, authenticated;
grant select on public.skills to anon, authenticated;
grant all privileges on public.agents to service_role;
grant all privileges on public.skills to service_role;

notify pgrst, 'reload schema';
