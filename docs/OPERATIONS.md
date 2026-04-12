# Borg Universe Betriebshinweise

Diese Hinweise gelten fuer die lokale Non-Production-Umgebung.

## Start und Pruefung

```powershell
docker compose up -d --build
docker compose ps
```

Erwartung:

- `web`, `mcp`, `worker`, `supabase-db` und `supabase-rest` laufen.
- `web`, `mcp`, `worker` und `supabase-db` sind `healthy`.
- UI: `http://127.0.0.1:8000/tasks`
- MCP: `http://127.0.0.1:9000/tools`
- PostgREST: `http://127.0.0.1:54321`

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m compileall app mcp_server main.py
```

Die Tests decken API-Basics, Repositories, MCP-Tools, Audit-Logging und Manifest-Validierung ab.

## Supabase-Backup

Lokaler Dump:

```powershell
docker compose exec -T supabase-db pg_dump -U supabase_admin -d postgres > backups\borg-universe-local.sql
```

Restore in eine frische lokale Umgebung:

```powershell
Get-Content backups\borg-universe-local.sql | docker compose exec -T supabase-db psql -U supabase_admin -d postgres
```

Vor Restore-Vorgaengen Containerzustand und Zielumgebung pruefen. Diese Umgebung ist nicht fuer Production-Daten vorgesehen.

## Audit und Zugriff

- Agenten und Skills muessen `requires_supabase_project_lookup=true` verwenden.
- `allowed_supabase_scopes` darf nur bekannte Scopes enthalten: `project_context`, `knowledge`, `rules`, `examples`.
- MCP-Tool-Aufrufe schreiben Audit-Eintraege nach `mcp_access_logs`.
- Fehlerhafte MCP-Aufrufe werden ebenfalls mit `success=false` protokolliert.
- UI-Audit: `http://127.0.0.1:8000/audit`

## Datenpflege

- Wissen: `/knowledge`
- Regeln: `/rules`
- Codebeispiele: `/examples`
- Agenten: `/agents`
- Skills: `/skills`

## Grenzen

- Keine Production-Konfiguration.
- Keine Hardwarezugriffe oder Toolchain-Ausfuehrung.
- Keine Secrets in Manifesten oder Testdaten speichern.
