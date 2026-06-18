"""
claudebench — token footprint measurement for ~/.claude/ config.

Public surface (Phase 1):
  models   — frozen dataclasses: Component, Snapshot, build_snapshot
  scanner  — scan(config_dir: Path) -> list[Component]
  snapshot — save, load, find_latest
"""
