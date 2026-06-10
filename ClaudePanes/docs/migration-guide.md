# Migration Guide

## Purpose

This document tracks breaking changes between minor versions of ClaudePanes. It is intended for users updating their TOML layout files or scripts that invoke the CLI. Each entry describes what changed, what the layout looked like before, what it should look like after, and the steps required to migrate. Non-breaking additions are documented in `CHANGELOG.md` instead.

## Versioning policy

ClaudePanes follows semantic versioning (`MAJOR.MINOR.PATCH`). While the project is pre-1.0, minor version bumps may include breaking changes to the TOML schema or CLI surface. Once 1.0 ships, breaking changes will be confined to major version bumps. Patch releases never break compatibility.

## v0.1.0

Initial release; no migrations apply.

Schema fingerprint (baseline for future diffs):

- Top-level fields: `name`, `description`, `terminal`, `working_dir`, `shell_prelude`
- Array-of-tables: `[[panes]]`, `[[tabs]]`

Future entries should diff against this baseline.

## How to read future entries

Each future migration entry will follow this format:

### vX.Y.Z

Short description of what changed and why.

**Before**

```toml
# Previous layout shape
name = "example"
old_field = "value"
```

**After**

```toml
# New layout shape
name = "example"
new_field = "value"
```

**How to migrate**

1. Step-by-step instructions for updating an existing layout.
2. Any CLI flags or scripts that need updating.
3. Notes on backward-compatible fallbacks, if applicable.

## Deprecation policy

When a field or flag is deprecated, ClaudePanes will emit a warning at load time but continue to honor the old behavior for at least one minor version. Removal happens no earlier than the following minor version, and is recorded as a migration entry above. Deprecation warnings include a pointer to this guide.
