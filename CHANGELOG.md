# Changelog

All notable changes to this project are documented in this file.

## [1.2.0] - 2026-11-18

### Added

- "Needs you" state: blocked tasks with Hermes `block_kind = needs_input`
  are counted separately (`needs_input` per board), shown in the chip
  ("N need you" or a `!N` badge next to a running title) and listed first
  among blocked tasks in the popup, in a configurable `attentionColor`.
- Popup: data age ("updated 12s ago"), the reason a host is offline/broken,
  heartbeat age and run time per running task, todo counts, and a "+N more"
  line instead of silently cutting the task list.
- Popup: fully done/empty boards collapse into "+N quiet boards" (click to
  show); unreadable boards stay visible.
- IPC `status` now reports `needsInput`, `unreadable` and `ageSec`.

### Fixed

- WAL boards whose `-shm`/`-wal` files are absent could not be opened
  read-only on macOS SQLite ("unable to open database file") and showed as
  `io` errors. Such boards are now re-opened with `immutable=1` — only when
  no `-wal` content exists, still strictly read-only.
- 0-byte `kanban.db` placeholders are skipped instead of reported as schema
  errors; duplicate board names get a numeric suffix.
- Collector stays Python 3.9 compatible for macOS system Python remotes.

## [1.1.0] - 2026-09-27

First public/community release. Community plugin — not affiliated with
Omarchy or 37signals.

### Added

- Optional remote machine monitoring over a user-preconfigured SSH alias
  (strict host key checking, batch mode); disabled by default and shown as
  "not configured" until enabled.
- External configuration file (`~/.config/omarchy-kanban/config.json`,
  `XDG_CONFIG_HOME` respected; a non-default path can be set via the
  `configPath` bar setting).
- Configurable chip accent colors (`pcColor`, `macColor`) with neutral
  default labels Local/Remote (internal `pc`/`mac` identifiers retained for
  compatibility).
- `reduceMotion` setting to disable the activity-bar animation.
- Stale-heartbeat indication: chips and the popup visibly say "Stale /
  unknown heartbeat" instead of silently showing old data as fresh; host
  connection state is reported separately from heartbeat freshness.
- IPC readback (`quickshell ipc ... call hendkai.kanban-progress status`)
  for independent verification of both hosts.
- English UI and documentation; backend unit tests and CI (Python 3.10 and
  3.14: unittest + compileall).

### Changed

- Remote polls are fully skipped when the remote chip is hidden
  (`showMac=false`).
- Rotating running-task titles no longer reset to the first title on every
  poll; the rotation position is preserved across refreshes.
- Chip title width is lower-bounded so long labels can no longer produce a
  negative elided text width; dynamic text elides within the chip.
- All task titles and board names render as plain text.

### Fixed

- Removed a disabled duplicate IPC handler in the popup that duplicated the
  bar widget's IPC target ownership.
