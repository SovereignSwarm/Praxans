# Devlog Agent Guide

> **Purpose**: Operating instructions for LLM agents working on the Thonglets/Praxans repository.
> Read this file first before making any changes to the devlog.

---

## File Map

| File | Purpose | Update Frequency |
|------|---------|-----------------|
| `PRODUCTION_LOG.md` | Chronological chronicle of every significant event | After every work session |
| `SYSTEM_REGISTRY.md` | Lookup table of all game systems, files, status | When systems are added/modified/removed |
| `DECISIONS.md` | Architectural Decision Records (ADRs) | When a non-trivial design choice is made |
| `CHANGELOG.md` | Grouped list of changes by development phase | After every work session |
| `AGENT_GUIDE.md` | This file — how to use the devlog | Rarely |

---

## How to Add a Production Log Entry

Append a new entry **at the top** of the `## Log` section in `PRODUCTION_LOG.md`. Use this template:

```markdown
### [YYYY-MM-DD] Title of Change

- **type**: milestone | feature | refactor | bugfix | infrastructure | content | audit
- **systems**: comma-separated system_ids from SYSTEM_REGISTRY.md
- **files**: key files created or modified (basenames only)
- **agent**: agent name or "human" if done by the developer

Summary of what happened in 1–3 sentences. Reference related decisions
with → ADR-NNN and related systems with → system_id.
```

### Rules

1. **Reverse chronological** — newest entries first.
2. **One entry per logical unit of work** — not per file edit.
3. **Use system_ids** from `SYSTEM_REGISTRY.md` in the `systems:` field.
4. **Keep summaries factual and concise** — no subjective commentary.
5. **Use ISO 8601 dates** — `YYYY-MM-DD`.

---

## How to Add a Decision Record

Append a new entry **at the bottom** of the `## Records` section in `DECISIONS.md`. Use the next sequential ADR number.

```markdown
### ADR-NNN: Title

- **date**: YYYY-MM-DD
- **status**: proposed | accepted | superseded | deprecated
- **context**: Why this decision was needed (1–3 sentences).
- **decision**: What was decided (1–3 sentences).
- **alternatives**: What else was considered and why it was rejected.
- **consequences**: What this means going forward.
```

### Rules

1. **Never delete or modify** an accepted ADR — mark it `superseded` and create a new one referencing it.
2. **Link from PRODUCTION_LOG.md** entries using `→ ADR-NNN`.

---

## How to Update the System Registry

Edit the relevant section in `SYSTEM_REGISTRY.md`. Each system entry looks like:

```markdown
### system_id

- **name**: Human-readable name
- **status**: active | experimental | deprecated | stub
- **package**: package/ or root
- **files**: list of key files (relative paths)
- **dependencies**: list of system_ids this system depends on
- **dependents**: list of system_ids that depend on this system
- **known_issues**: brief list or "none"
- **last_touched**: YYYY-MM-DD
```

### Rules

1. **Always update `last_touched`** when editing a system's files.
2. **Add new systems** when new packages/modules are introduced.
3. **Mark deprecated systems** — never silently remove entries.

---

## How to Update the Changelog

Add items to the current phase section at the top of `CHANGELOG.md`. If a new development phase begins, create a new section header.

```markdown
## [Phase Name] — YYYY-MM-DD to present

### Added
- Item description (→ system_id)

### Changed
- Item description

### Fixed
- Item description

### Removed
- Item description
```

---

## Cross-Reference Syntax

Use these conventions so agents can grep for connections:

| Syntax | Meaning | Example |
|--------|---------|---------|
| `→ ADR-NNN` | Links to a decision record | `→ ADR-003` |
| `→ system_id` | Links to a system registry entry | `→ llm_scheduler` |
| `→ CHANGELOG#phase` | Links to a changelog phase | `→ CHANGELOG#architecture-refactor` |
| `→ PROD-YYYY-MM-DD` | Links to a production log date | `→ PROD-2026-03-06` |

---

## Post-Work Checklist

After any work session, an agent should:

1. [ ] Add entry to `PRODUCTION_LOG.md`
2. [ ] Update `last_touched` dates in `SYSTEM_REGISTRY.md` for modified systems
3. [ ] Add items to the current phase in `CHANGELOG.md`
4. [ ] If a design decision was made, add an ADR to `DECISIONS.md`
5. [ ] Update `CLAUDE.md` if architecture, conventions, or key state changed
