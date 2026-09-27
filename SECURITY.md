# Security Policy

## Supported versions

Only the latest release line receives security fixes.

## Reporting a vulnerability

Please report suspected vulnerabilities privately via
[GitHub security advisories](https://github.com/hendkai/omarchy-kanban/security/advisories)
("Report a vulnerability"). Do not open public issues for security reports.

Include what you observed, steps to reproduce, affected version, and any
logs with personal data removed. Reports are reviewed on a best-effort
basis by a single maintainer; there is no committed response time.

## Scope notes

This plugin is a community project. It is not affiliated with, endorsed by,
or supported by Omarchy or 37signals.

Be aware of what the plugin inherently does before reporting expected
behavior as a vulnerability:

- Remote monitoring is strictly opt-in. When enabled, it runs the bundled
  read-only collector on the remote machine through your own preconfigured
  SSH alias, with your account permissions. Omarchy plugins are not
  sandboxed — install and enable plugins only from sources you trust.
- The collector opens kanban databases read-only, never writes task data,
  and sends no telemetry anywhere.
- SSH always uses strict host key checking and batch mode. Never disable
  host key verification to make a connection work.
