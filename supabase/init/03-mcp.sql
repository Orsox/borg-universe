-- Phase 5 MCP audit schema.

create table if not exists public.mcp_access_logs (
  id uuid primary key default extensions.gen_random_uuid(),
  agent_name text,
  skill_name text,
  tool_name text not null,
  query jsonb not null default '{}'::jsonb,
  result_count integer not null default 0,
  task_id uuid,
  project_id text,
  success boolean not null default true,
  error text,
  created_at timestamptz not null default now()
);

create index if not exists idx_mcp_access_logs_tool_created_at on public.mcp_access_logs(tool_name, created_at desc);
create index if not exists idx_mcp_access_logs_agent_created_at on public.mcp_access_logs(agent_name, created_at desc);
create index if not exists idx_mcp_access_logs_task_id on public.mcp_access_logs(task_id);

alter table public.mcp_access_logs enable row level security;

drop policy if exists "service role manages mcp access logs" on public.mcp_access_logs;
create policy "service role manages mcp access logs"
on public.mcp_access_logs for all
to service_role
using (true)
with check (true);

grant all privileges on public.mcp_access_logs to service_role;

notify pgrst, 'reload schema';
