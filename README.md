# omarchy-kanban

A community bar-widget plugin for [Omarchy](https://omarchy.org) that shows
read-only kanban progress for a **local** machine and an optional **remote**
machine — running task titles, running/blocked/ready counts, and a detail
popup with per-board numbers.

> **Community plugin.** Independent of — and not affiliated with, endorsed
> by, or supported by — Omarchy or 37signals. The plugin marketplace is an
> independent community effort.

## What it shows — progress vs. activity

The widget deliberately distinguishes two different things:

- **Activity** — the slim animated bar under a chip means tasks are in the
  `running` state *right now*. It says nothing about how far along a task is.
- **Progress** — counts only. The popup's "Board progress: X/Y" counts done
  versus tracked tasks per board (cancelled/archived excluded). These are
  snapshots of task counts, not estimates of work remaining.

**No percentages are ever shown.** A kanban status and a heartbeat cannot
express percent complete, so the plugin refuses to invent one. "Stale /
unknown heartbeat" means the newest running-task heartbeat is older than 10
minutes — data may be outdated; it is flagged, never silently shown as fresh.
Host connection status (connected / offline / error) is reported separately
from heartbeat freshness. When nothing runs, chips fall back to blocked and
ready counts ("3 blocked", "2 ready").

## Install

Standard plugin commands (from any directory):

```
omarchy plugin add https://github.com/hendkai/omarchy-kanban --enable
```

Remove again:

```
omarchy plugin remove hendkai.kanban-progress --yes
```

Installing or updating the plugin never touches your existing
`~/.config/omarchy-kanban/config.json` or any personal files.

### Manual install (optional)

```
git clone https://github.com/hendkai/omarchy-kanban ~/.config/omarchy/plugins/hendkai.kanban-progress
omarchy plugin validate ~/.config/omarchy/plugins/hendkai.kanban-progress
```

Then enable the widget via your bar configuration (`omarchy bar put`/`move`).
The widget polls `python3 poll.py` itself; no daemon, no root, no pip/npm.

## Configuration

Optional. Without a config file the widget just shows the local machine; the
remote chip reads "not configured" — not an error. Copy
[config.example.json](config.example.json) to
`~/.config/omarchy-kanban/config.json` (`XDG_CONFIG_HOME` is respected) and
edit it. A disabled remote is the default:

```json
{
  "local": { "hermesHome": "~/.hermes" },
  "remote": {
    "enabled": false,
    "host": "kanban-remote",
    "identityFile": "",
    "hostKeyAlias": "",
    "hermesHome": "~/.hermes"
  }
}
```

With `remote.enabled: true`, the plugin connects through **your own
preconfigured SSH alias** (`remote.host`) using batch mode and strict host
key checking. `remote.identityFile`/`hostKeyAlias` are optional extras.

### SSH setup (opt-in remote only)

1. **Verify the host key interactively first** — run `ssh <alias> true`
   yourself once from a normal terminal, over a trusted network, and confirm
   the fingerprint through a channel you trust. This pins the host key in
   `known_hosts`.
2. Configure the alias in `~/.ssh/config` (or a dedicated `IdentityFile`)
   with key authentication, e.g.:

   ```
   Host kanban-remote
     HostName your-host
     User you
     IdentityFile ~/.ssh/id_ed25519
   ```

3. Enable the remote in `config.json` and set `showMac` on the widget.

**Never** set `StrictHostKeyChecking=no` or accept an unverified host key to
make the connection work — that defeats host verification entirely.

### What SSH actually does (disclosure)

Remote monitoring pipes the bundled read-only `collector.py` source over SSH
to `python3 -` on the remote machine — nothing is installed there
persistently. That means SSH **executes code on the remote host with your
account's permissions** on every poll. The collector only opens kanban
databases read-only (SQLite), never writes task data, and sends no telemetry
anywhere. Omarchy plugins in general are **not sandboxed** — only enable
plugins from sources you trust.

## Bar settings

| Key              | Type    | Default              | Meaning                                                                   |
|------------------|---------|----------------------|---------------------------------------------------------------------------|
| `pollIntervalSec`| integer | `15`                 | Poll interval in seconds (10–300).                                        |
| `chipWidth`      | integer | `200`                | Chip width in px (90–400).                                                |
| `labelPc`        | string  | `Local`              | Label of the local chip (max 12 chars).                                   |
| `labelMac`       | string  | `Remote`             | Label of the remote chip (max 12 chars).                                  |
| `showMac`        | boolean | `true`               | Show the remote chip; `false` also stops all remote polls.                |
| `pcColor`        | string  | `#45d6c5` (turquoise)| Local chip accent color (`#rrggbb`).                                      |
| `macColor`       | string  | `#bd93f9` (violet)   | Remote chip accent color (`#rrggbb`).                                     |
| `reduceMotion`   | boolean | `false`              | Disable the activity-bar animation.                                       |
| `configPath`     | string  | *(empty = default)*  | Non-default config file path, passed to both poll processes.              |

Set from the command line, e.g.:

```
omarchy bar set hendkai.kanban-progress chipWidth 180
omarchy bar set hendkai.kanban-progress labelPc Desk
omarchy bar set hendkai.kanban-progress showMac false
```

The backend host identifiers remain `pc`/`mac` for compatibility; the UI
labels are configurable and default to Local/Remote.

## Safety & limitations

- **Stale running ≠ actual progress.** The activity bar marks running state,
  not advancement; counts are point-in-time snapshots.
- Read-only SQLite access; the plugin cannot create, modify, or delete tasks.
- No credentials, keys, hostnames, or personal data belong in this
  repository — keep them in your SSH/config files, which are never read by CI.
- Not security certified; single maintainer, best-effort fixes. See
  [SECURITY.md](SECURITY.md).
- Requires Python 3.10+ and an existing Omarchy (Quattro/Quickshell) shell;
  `ssh` is needed only for opt-in remote monitoring.

## Development

```
omarchy plugin validate .
python3 -m compileall poll.py collector.py
python3 -m unittest discover -s tests -v
```

Tests run against fixtures only — no live hosts, no user data. QML changes
can be checked by reloading the shell (`super+shift+r` on default Omarchy).
The IPC target `hendkai.kanban-progress` exposes `status` for live readback:

```
quickshell ipc -p /usr/share/omarchy/shell call hendkai.kanban-progress status
```

### AI-assisted development notice

This plugin was developed with AI assistance. Code and documentation were
produced with AI tools and verified by agent-operated tests on the maintainer's
live setup. No independent human code or security audit is claimed.

## License

[MIT](LICENSE) © 2026 hendkai.
