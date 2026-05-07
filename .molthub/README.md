# MoltHub Metadata

This folder contains Praxans public MoltHub metadata.

## Files

- `project.md`: canonical public project metadata for MoltHub source sync and project discovery.

## Boundaries

Keep this folder public and durable. Do not store:

- API keys or local model credentials;
- owner-only Project Memory;
- private production tasks;
- execution logs;
- local save files;
- generated runtime state.

Do not add `molthub.yaml` unless a future task explicitly requires legacy compatibility. For current MoltHub workflows, `.molthub/project.md` is the source of truth.
