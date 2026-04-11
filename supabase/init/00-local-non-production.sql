-- Local non-production Supabase-compatible bootstrap.
-- These roles and passwords are for Docker-based development only.

create schema if not exists extensions;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin;
  end if;

  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;

  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin bypassrls;
  end if;

  if not exists (select 1 from pg_roles where rolname = 'authenticator') then
    create role authenticator noinherit login password 'postgres';
  end if;
end
$$;

grant anon, authenticated, service_role to authenticator;
grant usage on schema public to anon, authenticated, service_role;
grant all privileges on schema public to service_role;

alter default privileges in schema public grant select, insert, update, delete on tables to authenticated;
alter default privileges in schema public grant select on tables to anon;
alter default privileges in schema public grant all privileges on tables to service_role;
alter default privileges in schema public grant usage, select on sequences to authenticated;
alter default privileges in schema public grant usage, select on sequences to service_role;

create table if not exists public.local_supabase_status (
  id integer primary key,
  environment text not null,
  note text not null,
  created_at timestamptz not null default now()
);

insert into public.local_supabase_status (id, environment, note)
values (1, 'non-production', 'Local Supabase-compatible stack for Borg Universe development.')
on conflict (id) do update
set environment = excluded.environment,
    note = excluded.note;

grant select on public.local_supabase_status to anon, authenticated;
grant all privileges on public.local_supabase_status to service_role;
