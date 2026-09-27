#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Poll wrapper for the hendkai.kanban-progress widget (version 1.1.0).

One invocation = one complete refresh of ONE host. QML runs two
independent subprocesses:

    python3 poll.py --host pc
    python3 poll.py --host mac

Output: exactly one JSON document on stdout:
  {"hosts": {"pc": {...}, "mac": {...}}}

Each host entry is the collector document (ok, generated_at, boards[])
plus _meta {"state": "ok"|"offline"|"error"|"disabled", "detail": ...}.
Exit code is 0 whenever a host entry was produced; exit 2 on usage or
pre-output IO errors.

Local ("pc"): runs the collector from THIS script's directory against the
local Hermes home.

Remote ("mac"): strictly opt-in. Nothing remote happens -- no subprocess,
no network, no ssh lookup -- unless config remote.enabled is true AND a
valid ssh host alias is configured. The collector source is piped to a
fixed `python3 -` on the remote over ssh with StrictHostKeyChecking=yes and
BatchMode=yes; the remote Hermes home is delivered as a safely encoded
JSON literal that replaces an argv placeholder -- it is never interpolated
into any command line, and the remote python3 never receives configuration
as its executable.

Config: user-local, never committed. Path resolution order:
  1. --config PATH           (explicit; useful for tests)
  2. $XDG_CONFIG_HOME/omarchy-kanban/config.json
  3. ~/.config/omarchy-kanban/config.json

Schema (config.example.json; all keys optional):
  {"local":  {"hermesHome": "~/.hermes"},
   "remote": {"enabled": false, "host": "kanban-remote",
              "identityFile": "", "hostKeyAlias": "",
              "hermesHome": "~/.hermes"}}

This file contains no usernames, IPs, or key paths; anything personal lives
only in the user's own config.
"""

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
COLLECTOR_PATH = os.path.join(HERE, "collector.py")

# Bounded: ConnectTimeout=5 + handshake + one fast collector run.
SSH_CONNECT_TIMEOUT = 5
SSH_TOTAL_TIMEOUT = 20

# argv placeholder replaced (as a whole element) with the encoded remote
# home before the collector's main() runs. It is a flag-shaped sentinel,
# not something ssh or a shell ever interprets.
HOME_ARG_SENTINEL = "__KANBAN_REMOTE_HOME__"

MAJOR, MINOR = sys.version_info[:2]
PY_3_10 = (MAJOR, MINOR) >= (3, 10)

if not PY_3_10:  # pragma: no cover
    sys.exit("poll.py requires Python 3.10+")

_META_DISABLED = {"state": "disabled", "detail": "remote not configured"}


def load_collector_source():
    with open(COLLECTOR_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


def expand_one(arg):
    """Expand a leading ~ in one argv entry; everything else verbatim."""
    if arg.startswith("~/") or arg == "~":
        return os.path.expanduser(arg)
    return arg


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

class ConfigError(Exception):
    pass


def default_config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "omarchy-kanban", "config.json")


def load_config(path):
    """Load and validate the user config; raise ConfigError on malformed.

    Empty/absent values are treated exactly like a missing config so a
    half-edited file never falls back to private defaults.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError):
        raise ConfigError("cannot read config: %s" % path)
    except ValueError as exc:
        raise ConfigError("malformed config JSON: %s" % exc)
    if not isinstance(doc, dict):
        raise ConfigError("config top level must be an object")
    return doc


def config_section(doc, key):
    sec = doc.get(key, {})
    if sec is None:
        sec = {}
    if not isinstance(sec, dict):
        raise ConfigError("config section '%s' must be an object" % key)
    return sec


def get_path_field(sec, default):
    value = sec.get("hermesHome", default)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("hermesHome must be a non-empty string")
    return value


def get_opt_str(sec, key):
    value = sec.get(key, "") or ""
    if not isinstance(value, str):
        raise ConfigError("config field '%s' must be a string" % key)
    return value


# --------------------------------------------------------------------------
# Host validation
# --------------------------------------------------------------------------

def is_valid_host(host):
    """True for a plausible ssh destination: [user@]hostname.

    Allows letters, digits, dots, hyphens (not leading), one '@' with a
    non-empty user part, and IPv6 literals in brackets. Rejects leading
    hyphens, whitespace, control characters, and shell metacharacters, so
    a configured host can never inject extra ssh options or commands.
    """
    if not isinstance(host, str) or not host:
        return False
    if any(c in host for c in "`$;|&<>(){}[]'\"\\*?!~"):
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in host):
        return False
    if host != host.strip() or host.startswith("-"):
        return False
    if host.count("@") > 1:
        return False
    user, _, hostname = host.rpartition("@") if "@" in host else ("", "", host)
    if "@" in host:
        if not user or not user.strip():
            return False
        if user.startswith("-"):
            return False
        if any(not (c.isalnum() or c in "-._") for c in user):
            return False
    return bool(hostname) and all(c.isalnum() or c in "-." for c in hostname)


# --------------------------------------------------------------------------
# Local host
# --------------------------------------------------------------------------

def collect_local(hermes_home):
    """Run the collector in-process against a local Hermes home."""
    sys.path.insert(0, HERE)
    try:
        import collector
        doc = collector.collect(os.path.expanduser(hermes_home))
    except Exception as exc:  # never crash the whole poll document
        doc = {
            "ok": False,
            "generated_at": int(time.time()),
            "boards": [],
            "_meta": {"state": "error", "detail": "collector: %s" % exc},
        }
    finally:
        sys.path.pop(0)
    return doc


# --------------------------------------------------------------------------
# Remote host
# --------------------------------------------------------------------------

def build_ssh_command(remote):
    """Build the bounded, read-only ssh argv from the remote config section."""
    argv = ["ssh"]
    identity = remote.get("identityFile") or ""
    if identity:
        argv += ["-i", identity]
    alias = remote.get("hostKeyAlias") or ""
    if alias:
        argv += ["-o", "HostKeyAlias=%s" % alias]
    argv += [
        "-o", "StrictHostKeyChecking=yes",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=%d" % SSH_CONNECT_TIMEOUT,
    ]
    argv.append(remote["host"])
    # Fixed remote command: collector source arrives on stdin, home arrives
    # as a replaced argv placeholder inside that source. Never a shell.
    argv += ["python3", "-"]
    return [expand_one(a) for a in argv]


def encode_remote_bootstrap(remote_home):
    """Build the safe remote payload: collector source + encoded home.

    The remote Hermes home is JSON-encoded and spliced into the source as a
    literal that replaces the sentinel argv element, so the value is parsed
    by python's json module on the far side -- there is no string
    interpolation into any command line, and no config value ever becomes
    part of the remote executable.
    """
    code = load_collector_source()
    # Double-encoded: the outer json.dumps yields a Python string literal
    # that EVALUATES to a valid JSON document (quotes intact), so the remote
    # json.loads always receives well-formed JSON regardless of the home
    # path's content (quotes, backslashes, unicode, spaces).
    encoded = json.dumps(json.dumps(remote_home))
    bootstrap = (
        "import sys, json\n"
        "argv = sys.argv[1:]\n"
        "try:\n"
        "    i = argv.index(%s)\n"
        "except ValueError:\n"
        "    i = -1\n"
        "if i >= 0:\n"
        "    argv[i] = json.loads(%s)\n"
        "sys.argv = sys.argv[:1] + argv\n"
        % (json.dumps(HOME_ARG_SENTINEL), encoded)
    )
    return bootstrap + code, HOME_ARG_SENTINEL


def collect_remote(remote):
    code, sentinel = encode_remote_bootstrap(remote["hermesHome"])
    argv = build_ssh_command(remote) + ["--hermes-home", sentinel]
    started = time.time()
    try:
        proc = subprocess.run(
            argv,
            input=code,
            capture_output=True,
            text=True,
            timeout=SSH_TOTAL_TIMEOUT,
        )
    except FileNotFoundError:
        return _err_host("offline", "ssh executable not found")
    except subprocess.TimeoutExpired:
        return _err_host("offline", "ssh timeout after %ds" % SSH_TOTAL_TIMEOUT)
    except OSError as exc:
        return _err_host("offline", str(exc))
    elapsed = int(time.time() - started)
    if proc.returncode != 0:
        detail = ("rc=%d %s" % (proc.returncode, (proc.stderr or "")[-300:])).strip()
        return _err_host("offline", detail, elapsed)
    try:
        doc = json.loads(proc.stdout)
    except ValueError as exc:
        return _err_host("error", "parse: %s" % exc, elapsed)
    if (not isinstance(doc, dict) or not isinstance(doc.get("ok"), bool)
            or not isinstance(doc.get("boards"), list)
            or not isinstance(doc.get("_meta", {}), dict)):
        return _err_host("error", "invalid remote response schema", elapsed)
    doc.setdefault("_meta", {})
    doc["_meta"]["state"] = doc.get("ok") and "ok" or "error"
    doc["_meta"]["elapsed_s"] = elapsed
    return doc


def _err_host(state, detail, elapsed=None):
    doc = {
        "ok": False,
        "generated_at": int(time.time()),
        "boards": [],
        "_meta": {"state": state, "detail": str(detail)[:300]},
    }
    if elapsed is not None:
        doc["_meta"]["elapsed_s"] = elapsed
    return doc


# --------------------------------------------------------------------------
# Entry
# --------------------------------------------------------------------------

def host_document(doc, host):
    """Produce one host entry from config or built-in defaults."""
    if host == "pc":
        local = config_section(doc or {}, "local")
        local_home = get_path_field(local, os.environ.get("HERMES_HOME") or "~/.hermes")
        return collect_local(local_home)

    remote = config_section(doc or {}, "remote")
    remote_home = get_path_field(remote, "~/.hermes")
    enabled = remote.get("enabled", False)
    if not isinstance(enabled, bool):
        return _err_host("error", "remote.enabled must be a boolean")
    if not enabled:
        return {"ok": False, "generated_at": int(time.time()),
                "boards": [], "_meta": dict(_META_DISABLED)}
    remote = dict(
        remote,
        host=get_opt_str(remote, "host"),
        identityFile=get_opt_str(remote, "identityFile"),
        hostKeyAlias=get_opt_str(remote, "hostKeyAlias"),
        hermesHome=remote_home,
    )
    if not is_valid_host(remote["host"]):
        return _err_host("error", "invalid or missing remote host in config")
    # An alias rides inside one "-o HostKeyAlias=<v>" element; OpenSSH joins
    # -o values with newlines, so a control character could smuggle in a
    # whole directive. Same charset rules as the host itself.
    if remote["hostKeyAlias"] and not is_valid_host(remote["hostKeyAlias"]):
        return _err_host("error", "invalid hostKeyAlias in config")
    return collect_remote(remote)


def main(argv=None):
    parser = argparse.ArgumentParser(description="kanban-progress poll wrapper")
    parser.add_argument("--host", choices=["pc", "mac"], required=True,
                        help="collect exactly one host (QML runs one process per host)")
    parser.add_argument("--config", default=None,
                        help="path to config.json (default: XDG config path)")
    args = parser.parse_args(argv)

    path = args.config or default_config_path()
    try:
        doc = load_config(path)
    except ConfigError as exc:
        hosts = {args.host: _err_host("error", str(exc))}
        json.dump({"hosts": hosts}, sys.stdout, separators=(",", ":"))
        sys.stdout.write("\n")
        return 0

    try:
        entry = host_document(doc, args.host)
    except ConfigError as exc:
        entry = _err_host("error", str(exc))
    hosts = {args.host: entry}
    json.dump({"hosts": hosts}, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
