#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only Hermes kanban board collector.

Plugin: hendkai.kanban-progress, version 1.2.0.
Stdlib only, Python 3.9+ (the remote side may be macOS system Python 3.9;
tested through 3.14). Generic: no usernames,
hosts, IPs, or key paths are embedded anywhere in this file.

Hermes home resolution, on whichever machine executes this script:
  1. --hermes-home PATH  (explicit)
  2. HERMES_HOME environment variable
  3. ~/.hermes           (default)

Discovery (bounded, deduplicated by realpath):
  <home>/kanban.db
  <home>/kanban/kanban.db
  <home>/kanban/boards/<name>/kanban.db

Configured-home semantics (deliberate, tested):
  - Home directory EXISTS but holds no boards -> ok=true, boards=[] (an
    existing, idle installation is "empty", not an error).
  - Home directory MISSING or not a directory -> ok=false and
    _meta.state="error" with detail "hermes home not found: <path>" (a
    configured-but-absent home is an error, never silently "no tasks").

Strictly read-only: every database is opened via SQLite URI mode=ro with
PRAGMA query_only=1 (WAL-safe). Some SQLite builds (macOS) refuse mode=ro
on a WAL database whose -shm/-wal files are absent (cleanly closed). Only
then, and only while no -wal file exists (nothing uncheckpointed), the board
is re-opened with immutable=1 -- still read-only, never creates files.
Empty (0-byte) kanban.db files are not boards and are skipped. No file, database, or directory is ever
created or modified; there is no disk cache. All connections are closed.
Counts for a board come from one query inside one implicit read
transaction, so status_counts/total/active are consistent for that board.

Output (stdout, exactly one JSON object):
  {"ok": true, "generated_at": <epoch seconds>, "boards": [...],
   "_meta": {"state": "ok"|"error", "detail": "..."}}

Board object:
  {"name": ..., "ok": true,
   "status_counts": {"running": 1, "weird-status": 2, ...},   # UNKNOWN
                                                   # statuses are counted
   "total": <denominator>,      # every status EXCEPT cancelled/archived
   "active": [ {"id", "title", "status", "block_kind", "heartbeat_at",
                "started_at"} ],
   "needs_input": <blocked tasks with block_kind needs_input>,
   "last_heartbeat_at": <epoch seconds or null>,
   "error": null}
  or on failure {"name": ..., "ok": false, "error": "schema"|"io"}.

  - active lists only running/review/blocked/ready tasks, priority-ordered
    (running, review, blocked needing input, other blocked, ready), then
    newest heartbeat first, LIMITed.
  - block_kind is null when the board schema predates the column.
  - heartbeat values are epoch SECONDS (Hermes stores seconds). Nulls are
    passed through as null; malformed values degrade to null, never crash.
  - An unexpected schema or unreadable board yields an EXPLICIT per-board
    error; the remaining boards and the host document survive untouched.
  - There is NO percentage anywhere: status counts cannot imply task
    progress. Counts are counts.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse

# Bounds so a pathological board can never stall a poll.
MAX_BOARDS = 40
MAX_ACTIVE_TASKS = 15
QUERY_TIMEOUT_MS = 4000

# Statuses pulled into the detail list. Everything else is only counted.
ACTIVE_STATUSES = ("running", "review", "blocked", "ready")

# Excluded from the "total" denominator only (still shown in status_counts).
EXCLUDED_STATUSES = ("cancelled", "archived")


def resolve_hermes_home(explicit=None):
    """Resolve the Hermes home: --hermes-home, else $HERMES_HOME, else ~/.hermes.

    '~' is expanded on the machine executing this script.
    """
    raw = explicit
    if raw is None:
        raw = os.environ.get("HERMES_HOME")
    if raw is None:
        raw = "~/.hermes"
    return os.path.expanduser(raw)


def discover_board_dbs(home):
    """Return bounded, realpath-deduplicated (name, path) pairs under home."""
    found = []
    seen = set()

    names = set()

    def add(name, path):
        real = os.path.realpath(path)
        if real in seen:
            return
        try:
            # A 0-byte file is a placeholder, not a board (it has no schema).
            if os.path.getsize(path) == 0:
                return
        except OSError:
            pass  # unreadable -> collect_board reports it explicitly
        seen.add(real)
        unique = name
        n = 2
        while unique in names:
            unique = "%s-%d" % (name, n)
            n += 1
        names.add(unique)
        found.append((unique, path))

    default_db = os.path.join(home, "kanban.db")
    if os.path.isfile(default_db):
        add("kanban", default_db)

    nested_default = os.path.join(home, "kanban", "kanban.db")
    if os.path.isfile(nested_default):
        add("kanban", nested_default)

    boards_dir = os.path.join(home, "kanban", "boards")
    if os.path.isdir(boards_dir):
        entries = sorted(os.listdir(boards_dir))
        for entry in entries:
            if len(found) >= MAX_BOARDS:
                break
            db = os.path.join(boards_dir, entry, "kanban.db")
            if os.path.isfile(db):
                add(entry, db)
    return found


def _connect(path, immutable):
    # URI-quote the whole path so '?', '#', '%' in board names survive.
    quoted = urllib.parse.quote(os.path.abspath(path))
    uri = "file:" + quoted + "?mode=ro" + ("&immutable=1" if immutable else "")
    con = sqlite3.connect(uri, uri=True, timeout=2.0)
    try:
        con.execute("PRAGMA query_only = 1")
        # SELECT alone does not start a persistent transaction in sqlite3's
        # legacy mode. Keep count and detail queries on the same WAL snapshot.
        con.execute("BEGIN")
        # Force the lazy open now so a refused WAL open surfaces here.
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except Exception:
        con.close()
        raise
    return con


def open_ro(path):
    """Open a sqlite database strictly read-only (WAL-safe, no copies)."""
    try:
        con = _connect(path, immutable=False)
    except sqlite3.OperationalError as exc:
        wal = path + "-wal"
        wal_pending = os.path.exists(wal) and os.path.getsize(wal) > 0
        if "unable to open" not in str(exc).lower() or wal_pending:
            raise
        # Cleanly closed WAL database on an SQLite build that cannot create
        # the -shm for a read-only handle: no -wal content exists, so the
        # main file is complete. immutable=1 reads it without any locking
        # or file creation.
        con = _connect(path, immutable=True)
    # Monotonic deadline: any single query exceeding it aborts as "io".
    deadline = time.monotonic() + QUERY_TIMEOUT_MS / 1000.0

    def _guard():
        return None if time.monotonic() < deadline else 1

    con.set_progress_handler(_guard, 500)
    return con


def safe_epoch(value):
    """Coerce a heartbeat/timestamp to int seconds; None/garbage -> None."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def collect_board(name, path):
    """Collect one board. Never raises; always returns a board dict."""
    board = {"name": name, "ok": False, "error": None}
    con = None
    try:
        con = open_ro(path)
        cur = con.cursor()

        # Schema probe before anything else: a file that is not our schema
        # (or not a database at all) must surface as "schema", never as an
        # empty board ("no tasks"). Missing expected columns count too.
        try:
            cur.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='tasks'"
            )
            if cur.fetchone()[0] != 1:
                board["error"] = "schema"
                return board
            cur.execute(
                "SELECT id, title, status, last_heartbeat_at, started_at FROM tasks LIMIT 0"
            )
            cur.fetchall()
            cur.execute("PRAGMA table_info(tasks)")
            has_block_kind = any(r[1] == "block_kind" for r in cur.fetchall())
            cur.execute("SELECT status, count(*) FROM tasks GROUP BY status")
            counts = {}
            total = 0
            for status, n in cur.fetchall():
                key = str(status) if status is not None else "unknown"
                counts[key] = counts.get(key, 0) + int(n)
                # The done-fraction denominator counts tracked statuses only:
                # cancelled/archived are excluded here AND in the QML, so
                # "done/total" can never disagree between the two.
                if key not in EXCLUDED_STATUSES:
                    total += int(n)
        except sqlite3.Error as exc:
            msg = str(exc).lower()
            if "no such" in msg or "file is not a database" in msg:
                board["error"] = "schema"
                return board
            raise

        board["status_counts"] = counts
        board["total"] = total

        needs_input = 0
        if has_block_kind:
            cur.execute(
                "SELECT count(*) FROM tasks "
                "WHERE status = 'blocked' AND block_kind = 'needs_input'"
            )
            needs_input = int(cur.fetchone()[0] or 0)
        board["needs_input"] = needs_input

        kind_col = "block_kind" if has_block_kind else "NULL"
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        cur.execute(
            "SELECT id, title, status, last_heartbeat_at, started_at, %s "
            "FROM tasks WHERE status IN (%s) "
            "ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'review' THEN 1 "
            "WHEN 'blocked' THEN (CASE WHEN %s = 'needs_input' THEN 2 ELSE 3 END) "
            "WHEN 'ready' THEN 4 ELSE 5 END, "
            "last_heartbeat_at IS NULL, last_heartbeat_at DESC "
            "LIMIT %d" % (kind_col, placeholders, kind_col, MAX_ACTIVE_TASKS),
            ACTIVE_STATUSES,
        )
        active = []
        last_hb = None
        for tid, title, status, hb, started, kind in cur.fetchall():
            hb_s = safe_epoch(hb)
            started_s = safe_epoch(started)
            active.append(
                {
                    "id": str(tid),
                    # Titles pass through verbatim: QML renders PlainText,
                    # so newlines/HTML can never inject. Clamped only for
                    # transport size.
                    "title": str(title)[:300] if title is not None else "",
                    "status": str(status) if status is not None else "unknown",
                    # Only meaningful while blocked; running tasks keep a
                    # stale block_kind from an earlier block.
                    "block_kind": (str(kind)[:40] if kind is not None
                                   and status == "blocked" else None),
                    "heartbeat_at": hb_s,
                    "started_at": started_s,
                }
            )
            if status == "running" and hb_s is not None:
                if last_hb is None or hb_s > last_hb:
                    last_hb = hb_s
        board["active"] = active
        board["last_heartbeat_at"] = last_hb
        board["ok"] = True
        return board
    except sqlite3.OperationalError:
        board["error"] = "io"
        return board
    except sqlite3.DatabaseError:
        board["error"] = "schema"
        return board
    except Exception:
        # Malformed data must never take down the whole host document.
        board["error"] = "io"
        return board
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass


def collect(home):
    """Collect every board under a Hermes home; build the host document."""
    if not os.path.isdir(home):
        return {
            "ok": False,
            "generated_at": int(time.time()),
            "boards": [],
            "_meta": {
                "state": "error",
                "detail": "hermes home not found: %s" % home,
            },
        }
    boards = []
    deadline = time.monotonic() + 10.0
    try:
        discovered = discover_board_dbs(home)
    except OSError as exc:
        return {"ok": False, "generated_at": int(time.time()), "boards": [],
                "_meta": {"state": "error", "detail": "board discovery: %s" % exc}}
    for name, path in discovered:
        if time.monotonic() >= deadline:
            return {"ok": False, "generated_at": int(time.time()), "boards": boards,
                    "_meta": {"state": "error", "detail": "collection deadline exceeded"}}
        boards.append(collect_board(name, path))
        if len(boards) >= MAX_BOARDS:
            break
    return {
        "ok": True,
        "generated_at": int(time.time()),
        "boards": boards,
        "_meta": {"state": "ok"},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Hermes kanban read-only collector")
    parser.add_argument(
        "--hermes-home",
        default=None,
        help="Hermes home directory (default: $HERMES_HOME or ~/.hermes)",
    )
    args = parser.parse_args(argv)
    json.dump(collect(resolve_hermes_home(args.hermes_home)), sys.stdout,
              separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
