-- Phase 4 local knowledge-management schema and seed content.

create table if not exists public.knowledge_entries (
  id uuid primary key default extensions.gen_random_uuid(),
  title text not null,
  domain text,
  platform text,
  mcu_family text,
  peripheral text,
  content text not null,
  source text,
  quality_level text,
  tags text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.rules (
  id uuid primary key default extensions.gen_random_uuid(),
  name text not null,
  scope text,
  severity text not null default 'info',
  rule_text text not null,
  applies_to text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.code_examples (
  id uuid primary key default extensions.gen_random_uuid(),
  title text not null,
  platform text,
  framework text,
  language text,
  peripheral text,
  code text not null,
  explanation text,
  known_limitations text,
  tags text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'knowledge_entries_title_key') then
    alter table public.knowledge_entries add constraint knowledge_entries_title_key unique (title);
  end if;

  if not exists (select 1 from pg_constraint where conname = 'rules_name_key') then
    alter table public.rules add constraint rules_name_key unique (name);
  end if;

  if not exists (select 1 from pg_constraint where conname = 'code_examples_title_key') then
    alter table public.code_examples add constraint code_examples_title_key unique (title);
  end if;
end
$$;

drop trigger if exists knowledge_entries_set_updated_at on public.knowledge_entries;
create trigger knowledge_entries_set_updated_at
before update on public.knowledge_entries
for each row
execute function public.set_updated_at();

drop trigger if exists rules_set_updated_at on public.rules;
create trigger rules_set_updated_at
before update on public.rules
for each row
execute function public.set_updated_at();

drop trigger if exists code_examples_set_updated_at on public.code_examples;
create trigger code_examples_set_updated_at
before update on public.code_examples
for each row
execute function public.set_updated_at();

create index if not exists idx_knowledge_entries_platform on public.knowledge_entries(platform);
create index if not exists idx_knowledge_entries_mcu_family on public.knowledge_entries(mcu_family);
create index if not exists idx_knowledge_entries_peripheral on public.knowledge_entries(peripheral);
create index if not exists idx_knowledge_entries_tags on public.knowledge_entries using gin(tags);
create index if not exists idx_rules_scope on public.rules(scope);
create index if not exists idx_rules_applies_to on public.rules using gin(applies_to);
create index if not exists idx_code_examples_platform on public.code_examples(platform);
create index if not exists idx_code_examples_framework on public.code_examples(framework);
create index if not exists idx_code_examples_peripheral on public.code_examples(peripheral);
create index if not exists idx_code_examples_tags on public.code_examples using gin(tags);

alter table public.knowledge_entries enable row level security;
alter table public.rules enable row level security;
alter table public.code_examples enable row level security;

drop policy if exists "anon can read knowledge entries" on public.knowledge_entries;
create policy "anon can read knowledge entries"
on public.knowledge_entries for select
to anon
using (true);

drop policy if exists "service role manages knowledge entries" on public.knowledge_entries;
create policy "service role manages knowledge entries"
on public.knowledge_entries for all
to service_role
using (true)
with check (true);

drop policy if exists "anon can read rules" on public.rules;
create policy "anon can read rules"
on public.rules for select
to anon
using (true);

drop policy if exists "service role manages rules" on public.rules;
create policy "service role manages rules"
on public.rules for all
to service_role
using (true)
with check (true);

drop policy if exists "anon can read code examples" on public.code_examples;
create policy "anon can read code examples"
on public.code_examples for select
to anon
using (true);

drop policy if exists "service role manages code examples" on public.code_examples;
create policy "service role manages code examples"
on public.code_examples for all
to service_role
using (true)
with check (true);

grant select on public.knowledge_entries to anon, authenticated;
grant select on public.rules to anon, authenticated;
grant select on public.code_examples to anon, authenticated;
grant all privileges on public.knowledge_entries to service_role;
grant all privileges on public.rules to service_role;
grant all privileges on public.code_examples to service_role;

insert into public.knowledge_entries (
  title,
  domain,
  platform,
  mcu_family,
  peripheral,
  content,
  source,
  quality_level,
  tags
)
values
  (
    'STM32 SPI HAL initialization checklist',
    'embedded',
    'STM32',
    'STM32F4',
    'SPI',
    'Configure GPIO alternate functions, enable peripheral clocks, initialize SPI mode before enabling DMA, and keep chip-select handling explicit in user code blocks.',
    'local seed',
    'seed',
    array['stm32', 'spi', 'hal']
  ),
  (
    'Nordic Zephyr GPIO and SPI configuration pattern',
    'embedded',
    'Nordic',
    'nRF52',
    'SPI',
    'Use Devicetree overlays for pins and chip-select definitions, keep application code behind Zephyr device readiness checks, and avoid hard-coded GPIO numbers.',
    'local seed',
    'seed',
    array['nordic', 'zephyr', 'spi']
  )
on conflict (title) do update
set domain = excluded.domain,
    platform = excluded.platform,
    mcu_family = excluded.mcu_family,
    peripheral = excluded.peripheral,
    content = excluded.content,
    source = excluded.source,
    quality_level = excluded.quality_level,
    tags = excluded.tags;

insert into public.rules (
  name,
  scope,
  severity,
  rule_text,
  applies_to
)
values
  (
    'STM32 HAL user-code boundary',
    'stm32',
    'high',
    'Generated STM32 HAL files may only be changed inside defined user-code blocks unless the task explicitly approves generator-aware changes.',
    array['STM32', 'HAL']
  ),
  (
    'Nordic Zephyr Devicetree first',
    'nordic',
    'high',
    'Nordic and Zephyr hardware configuration must be represented through Devicetree overlays or Kconfig before application code assumes devices exist.',
    array['Nordic', 'Zephyr']
  )
on conflict (name) do update
set scope = excluded.scope,
    severity = excluded.severity,
    rule_text = excluded.rule_text,
    applies_to = excluded.applies_to;

insert into public.code_examples (
  title,
  platform,
  framework,
  language,
  peripheral,
  code,
  explanation,
  known_limitations,
  tags
)
values
  (
    'STM32 HAL SPI transmit skeleton',
    'STM32',
    'HAL',
    'C',
    'SPI',
    'HAL_GPIO_WritePin(CS_GPIO_Port, CS_Pin, GPIO_PIN_RESET);\nHAL_SPI_Transmit(&hspi1, buffer, size, timeout_ms);\nHAL_GPIO_WritePin(CS_GPIO_Port, CS_Pin, GPIO_PIN_SET);',
    'Minimal blocking SPI transfer pattern with explicit chip-select handling.',
    'Blocking transfer only; review timing before use in critical paths.',
    array['stm32', 'hal', 'spi']
  ),
  (
    'Zephyr SPI device readiness check',
    'Nordic',
    'Zephyr',
    'C',
    'SPI',
    'const struct device *spi_dev = DEVICE_DT_GET(DT_NODELABEL(spi1));\nif (!device_is_ready(spi_dev)) {\n    return -ENODEV;\n}',
    'Checks that a Zephyr SPI device from Devicetree is ready before use.',
    'Requires matching Devicetree node labels in the target board overlay.',
    array['nordic', 'zephyr', 'spi']
  )
on conflict (title) do update
set platform = excluded.platform,
    framework = excluded.framework,
    language = excluded.language,
    peripheral = excluded.peripheral,
    code = excluded.code,
    explanation = excluded.explanation,
    known_limitations = excluded.known_limitations,
    tags = excluded.tags;

notify pgrst, 'reload schema';
