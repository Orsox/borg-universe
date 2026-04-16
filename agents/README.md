# 🤖 Borg Agent Collective — Übersicht

> *Resistance is futile. Your code will be assimilated.*

---

## 📐 Architektur & Planung

| Agent | Zweck |
|---|---|
| **borg-queen-architect** | Entwirft Architektur & Modulstruktur auf Basis einer `borg-cube.md` — bevor Implementierung beginnt |
| **borg-disassembler** | Zerlegt ein Feature-Spec in ein strukturiertes, ausführbares Task-Backlog für nachgelagerte Agenten |
| **borg-git-orchestrator** | Verwaltet Branches, Worktrees und Workspace-Lifecycle für Claude Code Workflows |

---

## 📋 Spezifikation & Anforderungen

| Agent | Zweck |
|---|---|
| **borg-spec-assimilator** | Scannt bestehende Projekte, erzeugt Root- und Modul-`borg-cube.md`-Spezifikationen und beschreibt nur den Ist-Zustand |
| **borg-spec-augmentation** | Erweitert bestehende Specs proaktiv: Gap-Analyse, fehlende Edge Cases, schwache Akzeptanzkriterien, unklare Interfaces |
| **borg-requirement-node** | Reviewt `borg-cube.md`-Dateien auf Anforderungsqualität — bevor die Implementierung startet |

---

## ⚙️ Implementierung

| Agent | Zweck |
|---|---|
| **borg-neural-implant-feature** | Schreibt Produktionscode für ein Feature auf Basis einer `borg-cube.md`-Spezifikation |
| **borg-implementation-drone** | Führt Tasks aus einer Task-Liste strikt und deterministisch aus — Code, Tests, Doku |
| **borg-feature-integrator** | Integriert einen Augmentation-Handoff in eine bestehende Task-Liste oder legt eine neue an |

---

## 🧪 Testing

| Agent | Zweck |
|---|---|
| **borg-cube-testing-node** | Embedded-C Spezialist: erstellt & integriert Unity/CMock Unit Tests via CMake/CTest |
| **borg-drone-diagnostic** | Python Spezialist: erstellt & debuggt pytest-Suites, Edge-Case-Coverage, Mocking |
| **borg-regenerator** | Leitet Tests aus `borg-cube.md` ab, repariert oder erweitert bestehende Tests nach Refactoring |

---

## 📝 Dokumentation

| Agent | Zweck |
|---|---|
| **borg-interface-readme** | Generiert eine hochwertige `README.md` für ein Repository auf Basis von Projektstruktur & Feature-Specs |

---

## 🔄 Typischer Workflow

```
borg-queen-architect         →  Spec (borg-cube.md) & Architektur planen
  ↓  (max. 3 Korrekturzyklen bei Review-Fehlern)
borg-requirement-node        →  Spec reviewen & qualitätssichern
  ↓
borg-spec-assimilator        →  Bestehendes Projekt scannen und Root-/Modul-Specs erzeugen
  ↓
borg-spec-augmentation       →  Spec erweitern & lückenfüllen
  ↓
borg-disassembler            →  Tasks ableiten
  ↓
borg-implementation-drone    →  Tasks implementieren
borg-neural-implant-feature  →  Feature-Code schreiben
  ↓
borg-cube-testing-node       →  Embedded-C Tests
borg-drone-diagnostic        →  Python Tests
borg-regenerator             →  Tests reparieren / erweitern
  ↓
borg-interface-readme        →  README generieren
```
