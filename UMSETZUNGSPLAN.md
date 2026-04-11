# Abwicklungsplan: Borg Universe

## Ziel

Die Anwendung ist eine Docker-basierte FastAPI-Plattform zur Aufgabenverwaltung, Wissenspflege und kontrollierten Nutzung des bestehenden Borg-Agenten-Systems.

Das System ist spezialisiert auf konkrete Entwicklungsaufgaben rund um STM32- und Nordic-Mikrocontroller. Es führt keine eigenständigen Toolchain-, Build-, Flash- oder Hardwareaktionen aus. Stattdessen unterstützt es Agenten durch eine Supabase-Wissensbasis, definierte Regeln, Codebeispiele und einen kontrollierten MCP-Zugriff.

## Grundprinzipien

- Supabase dient als zentrale Wissensbasis und Audit-Speicher.
- Agenten greifen ausschliesslich ueber MCP auf Supabase zu.
- Agenten erhalten keinen direkten Datenbank-Key.
- Das lokale `BORG/`-Verzeichnis enthaelt Agenten, Skills, Regeln und Prompts.
- Agenten und Skills werden aktiv gepflegt und ueber Manifeste beschrieben.
- Aufgaben werden nachvollziehbar als Task-Verlauf dokumentiert.
- Ergebnisse werden als Vorschlaege, Codefragmente, Projektdateien oder Artefakte bereitgestellt.
- Kritische Ergebnisse gehen in einen Review-Status.
- Keine implizite Ausfuehrung von STM32CubeMX, Nordic Toolchain, Firmware-Builds, Flash-Vorgaengen oder Shell-Kommandos.

## Zielarchitektur

```text
FastAPI Web App
  Aufgabenuebersicht
  Wissensverwaltung
  Agenten- und Skill-Verwaltung
  Audit-Ansicht

Worker
  Task-Polling
  Agenten- und Skill-Aufrufe
  Ergebnisablage

MCP Server
  Kontrollierter Zugriff auf Supabase
  Tool-Schemas
  Audit-Logging

Supabase
  Tasks
  Regeln
  Wissen
  Codebeispiele
  Agenten-/Skill-Metadaten
  MCP-Zugriffslogs

BORG/
  Agenten
  Skills
  Regeln
  Prompts
  Manifeste
```

## Vorgeschlagene Projektstruktur

```text
borg-universe/
  app/
    main.py
    api/
      tasks.py
      knowledge.py
      agents.py
      skills.py
      mcp.py
    core/
      config.py
      security.py
      logging.py
    db/
      supabase_client.py
      repositories.py
    services/
      task_service.py
      knowledge_service.py
      borg_service.py
      artifact_service.py
    models/
    templates/
    static/

  mcp_server/
    server.py
    tools/
      knowledge_tools.py
      task_tools.py
      rule_tools.py
      skill_tools.py

  BORG/
    agents/
    skills/
    rules/
    prompts/
    manifests/

  artifacts/
  Dockerfile
  docker-compose.yml
  .env.example
  pyproject.toml
  README.md
```

## Supabase-Datenmodell

### `tasks`

Speichert konkrete Aufgabenanfragen.

Wichtige Felder:

- `id`
- `title`
- `description`
- `status`
- `target_platform`
- `target_mcu`
- `board`
- `topic`
- `requested_by`
- `assigned_agent`
- `assigned_skill`
- `created_at`
- `updated_at`

Statuswerte:

```text
draft
queued
running
needs_input
review_required
done
failed
cancelled
```

### `task_events`

Speichert den Verlauf einer Aufgabe.

Wichtige Felder:

- `id`
- `task_id`
- `event_type`
- `message`
- `payload`
- `created_at`

### `knowledge_entries`

Speichert technisches Wissen.

Wichtige Felder:

- `id`
- `title`
- `domain`
- `platform`
- `mcu_family`
- `peripheral`
- `content`
- `source`
- `quality_level`
- `tags`
- `created_at`
- `updated_at`

Beispiele:

- SPI Initialisierung fuer STM32 HAL
- SPI Zugriff unter Zephyr
- DMA-Regeln fuer STM32 UART
- nRF Connect SDK GPIO Pattern
- Bekannte Fehler bei Chip-Select-Handling

### `rules`

Speichert verbindliche Entwicklungsregeln.

Wichtige Felder:

- `id`
- `name`
- `scope`
- `severity`
- `rule_text`
- `applies_to`
- `created_at`
- `updated_at`

Beispiele:

- Keine blockierenden SPI-Transfers in zeitkritischen Pfaden.
- Nordic-/Zephyr-Konfiguration erfolgt ueber Devicetree Overlays.
- STM32 HAL-Code darf nur in definierten User-Code-Bloecken veraendert werden.
- Bei unklarer MCU-Variante muss der Agent eine Rueckfrage stellen.

### `code_examples`

Speichert strukturierte Codebeispiele.

Wichtige Felder:

- `id`
- `title`
- `platform`
- `framework`
- `language`
- `peripheral`
- `code`
- `explanation`
- `known_limitations`
- `tags`

### `agents`

Registrierte Borg-Agenten.

Wichtige Felder:

- `id`
- `name`
- `description`
- `path`
- `enabled`
- `version`
- `maintainer`
- `created_at`
- `updated_at`

### `skills`

Registrierte Skills.

Wichtige Felder:

- `id`
- `name`
- `description`
- `path`
- `enabled`
- `version`
- `input_schema`
- `output_schema`

### `mcp_access_logs`

Audit-Log fuer Agentenzugriffe.

Wichtige Felder:

- `id`
- `agent_name`
- `tool_name`
- `query`
- `result_count`
- `task_id`
- `created_at`

### `artifacts`

Speichert erzeugte Ergebnisse.

Wichtige Felder:

- `id`
- `task_id`
- `artifact_type`
- `path_or_storage_key`
- `checksum`
- `created_at`

## MCP-Tools

Agenten greifen ueber klar definierte MCP-Tools auf die Wissensbasis zu.

MCP-Tools fuer Version 1:

```text
knowledge.search
knowledge.get_entry
rules.search
examples.search
tasks.get
tasks.add_event
tasks.request_input
artifacts.create
agents.list
skills.list
```

Regeln fuer MCP-Zugriffe:

- Jeder Zugriff wird protokolliert.
- Schreiboperationen sind enger begrenzt als Leseoperationen.
- Task-bezogene Zugriffe muessen eine `task_id` enthalten.
- Agenten duerfen nur freigegebene Tools nutzen.
- Verbotene Aktionen werden ueber Manifeste dokumentiert und technisch blockiert, soweit moeglich.

## BORG-Verzeichnis

Das `BORG/`-Verzeichnis ist die aktiv gepflegte Agenten- und Skill-Basis.

Empfohlene Struktur:

```text
BORG/
  agents/
    stm32_agent/
      AGENT.md
      manifest.json
    nordic_agent/
      AGENT.md
      manifest.json
    reviewer_agent/
      AGENT.md
      manifest.json

  skills/
    spi_lookup/
      SKILL.md
      manifest.json
    zephyr_config_helper/
      SKILL.md
      manifest.json
    stm32_hal_advisor/
      SKILL.md
      manifest.json

  rules/
    global.md
    stm32.md
    nordic.md

  prompts/
    task_classifier.md
    code_reviewer.md

  tests/
    skill_cases/
    agent_cases/
```

Beispiel fuer ein Skill-Manifest:

```json
{
  "name": "stm32_hal_advisor",
  "version": "0.1.0",
  "description": "Supports STM32 HAL-related development tasks using Supabase knowledge via MCP.",
  "allowed_tools": [
    "knowledge.search",
    "rules.search",
    "examples.search",
    "tasks.add_event",
    "tasks.request_input",
    "artifacts.create"
  ],
  "forbidden_actions": [
    "build_firmware",
    "flash_device",
    "modify_external_repo",
    "run_shell_without_approval"
  ]
}
```

## Task-Lebenszyklus

1. Nutzer legt eine Aufgabe an.
2. System klassifiziert Plattform und Thema.
3. Passender Agent oder Skill wird zugewiesen.
4. Agent ruft ueber MCP passende Regeln, Beispiele und Wissenseintraege ab.
5. Agent erzeugt Antwort, Vorschlag, Codefragment, Projektdatei oder Rueckfrage.
6. Ergebnis wird im Task-Verlauf gespeichert.
7. Ergebnis geht je nach Risiko auf `review_required`, `needs_input` oder `done`.

## Uebersichtsseite

Die Anwendung startet direkt als Arbeitsoberflaeche.

Geplante Seiten:

```text
/
  Aufgabenuebersicht

/tasks/{id}
  Task-Details, Verlauf, Ergebnis, Rueckfragen

/knowledge
  Wissensbasis durchsuchen und pflegen

/rules
  Regeln verwalten

/examples
  Codebeispiele verwalten

/agents
  Agenten anzeigen und aktivieren/deaktivieren

/skills
  Skills anzeigen und aktivieren/deaktivieren

/audit
  MCP-Zugriffe pruefen
```

## Docker-Betriebsmodell

Empfohlene Container:

```text
web
  FastAPI und UI

worker
  Task-Verarbeitung und Agentenaufrufe

mcp
  MCP-Server fuer kontrollierten Supabase-Zugriff

supabase
  Extern gehostet oder lokal separat betrieben
```

Empfohlene Volumes:

```text
./BORG:/app/BORG
./artifacts:/app/artifacts
```

Wichtige Umgebungsvariablen:

```text
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_ANON_KEY=
BORG_ROOT=/app/BORG
ARTIFACT_ROOT=/app/artifacts
MCP_SERVER_URL=
```

## Umsetzungsphasen

### Phase 1: Fundament

- FastAPI-Projektstruktur aufbauen
- Dockerfile erstellen
- `docker-compose.yml` erstellen
- `.env.example` anlegen
- Healthcheck-Endpunkt bereitstellen
- Konfigurationssystem einfuehren

Akzeptanzkriterium:

- Die Anwendung startet per Docker Compose.
- Der Healthcheck ist erreichbar.

### Phase 2: Supabase-Anbindung

- Supabase-Client einrichten
- Tabellenmigrationen vorbereiten
- Repository-Schicht fuer Tasks, Wissen, Regeln und Beispiele erstellen
- Grundlegende Fehlerbehandlung einfuehren

Akzeptanzkriterium:

- Tasks und Wissenseintraege koennen gespeichert, gelesen und aktualisiert werden.

### Phase 3: Aufgabenverwaltung

- Task-API implementieren
- Task-Dashboard erstellen
- Task-Detailseite erstellen
- Task-Events sichtbar machen
- Statuswechsel implementieren

Akzeptanzkriterium:

- Nutzer kann eine Aufgabe anlegen und deren Verlauf einsehen.

### Phase 4: Wissensbasis

- CRUD fuer `knowledge_entries`
- CRUD fuer `rules`
- CRUD fuer `code_examples`
- Filter nach Plattform, Framework, Peripherie und Tags
- Erste Beispielinhalte fuer STM32 SPI und Nordic Zephyr anlegen

Akzeptanzkriterium:

- Wissen kann gepflegt und gezielt gesucht werden.

### Phase 5: MCP-Server

- MCP-Server implementieren
- Tool `knowledge.search` implementieren
- Tool `rules.search` implementieren
- Tool `examples.search` implementieren
- Tool `tasks.add_event` implementieren
- Audit-Logging implementieren

Akzeptanzkriterium:

- Ein Agent kann kontrolliert Wissen abrufen.
- Jeder Zugriff wird in Supabase protokolliert.

### Phase 6: BORG-Integration

- `BORG/`-Struktur anlegen
- Manifest-Scanner implementieren
- Agenten und Skills in der App anzeigen
- Aktivieren und Deaktivieren von Agenten/Skills ermoeglichen
- Mock-Agent fuer erste Ende-zu-Ende-Pruefung bauen

Akzeptanzkriterium:

- Die Anwendung erkennt lokale Agenten und Skills.
- Ein Mock-Agent kann eine Aufgabe mit MCP-Wissen bearbeiten.

### Phase 7: Agentische Bearbeitung

- Worker-Prozess implementieren
- Task-Polling implementieren
- Agenten-/Skill-Ausfuehrung anbinden
- Ergebnisse als Events und Artefakte speichern
- Rueckfragen als `needs_input` abbilden

Akzeptanzkriterium:

- Eine Beispielaufgabe zu STM32 SPI wird agentisch bearbeitet.
- Das Ergebnis ist nachvollziehbar und verweist auf verwendete Regeln und Wissenseintraege.

### Phase 8: UI und Pflege

- Aufgabenuebersicht fertigstellen
- Task-Detailansicht erweitern
- Wissensbasis-Editor erstellen
- Regelverwaltung erstellen
- Agenten-/Skill-Verwaltung erstellen
- Audit-Ansicht erstellen

Akzeptanzkriterium:

- Das System ist ohne CLI operativ nutzbar.

### Phase 9: Haertung

- API-Tests
- Repository-Tests
- MCP-Tool-Tests
- Manifest-Validierung
- Tests fuer verbotene Aktionen
- Dokumentation
- Backup- und Betriebshinweise

Akzeptanzkriterium:

- Kernfunktionen sind getestet.
- Zugriffsbeschraenkungen und Audit-Logging sind nachvollziehbar.

## Erster Sprint

Der erste Sprint soll die Architektur validieren, ohne die Generator- oder Toolchain-Komplexitaet vorwegzunehmen.

Aufgaben:

1. FastAPI-Struktur ausbauen.
2. Dockerfile und `docker-compose.yml` ergaenzen.
3. Supabase-Konfiguration einfuehren.
4. Tabellen fuer `tasks`, `task_events`, `knowledge_entries`, `rules` und `code_examples` definieren.
5. Einfache Aufgabenuebersicht erstellen.
6. `BORG/`-Grundstruktur anlegen.
7. MCP-Tool `knowledge.search` implementieren.
8. Mock-Agent bauen, der eine Aufgabe bearbeitet und Wissen aus Supabase nutzt.

Ergebnis:

- Aufgabe rein.
- Agent arbeitet begrenzt und nachvollziehbar.
- Supabase liefert Wissen.
- Ergebnis wird dokumentiert.
- Keine eigenstaendige Ausfuehrung von Toolchains oder Hardwareaktionen.
