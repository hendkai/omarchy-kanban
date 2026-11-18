#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for 1.2.0: WAL read-only fallback, needs_input, discovery."""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import collector  # noqa: E402

NEW_SCHEMA = """
CREATE TABLE tasks (
    id TEXT PRIMARY KEY, title TEXT, status TEXT,
    last_heartbeat_at INTEGER, started_at INTEGER, block_kind TEXT
);
"""


def make_new_db(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(NEW_SCHEMA)
    con.executemany("INSERT INTO tasks VALUES (?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="okb12-", dir=os.environ.get("TMPDIR"))
        self.home = os.path.join(self.tmp, "home")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestNeedsInput(Base):
    def test_needs_input_counted_and_ordered_first(self):
        make_new_db(os.path.join(self.home, "kanban", "boards", "a", "kanban.db"), [
            ("d1", "dep", "blocked", 1700000900, None, None),
            ("q1", "question", "blocked", None, None, "needs_input"),
            ("r1", "work", "running", 1700000000, 1690000000, "needs_input"),
            ("x1", "ok", "done", None, None, None),
        ])
        b = collector.collect(self.home)["boards"][0]
        self.assertTrue(b["ok"])
        self.assertEqual(b["needs_input"], 1)
        self.assertEqual([t["id"] for t in b["active"]], ["r1", "q1", "d1"])
        # stale block_kind on a running task is not reported
        self.assertIsNone(b["active"][0]["block_kind"])
        self.assertEqual(b["active"][1]["block_kind"], "needs_input")
        self.assertIsNone(b["active"][2]["block_kind"])

    def test_old_schema_without_block_kind(self):
        os.makedirs(self.home)
        con = sqlite3.connect(os.path.join(self.home, "kanban.db"))
        con.execute("CREATE TABLE tasks (id TEXT, title TEXT, status TEXT,"
                    " last_heartbeat_at INTEGER, started_at INTEGER)")
        con.execute("INSERT INTO tasks VALUES ('b','x','blocked',NULL,NULL)")
        con.commit()
        con.close()
        b = collector.collect(self.home)["boards"][0]
        self.assertTrue(b["ok"])
        self.assertEqual(b["needs_input"], 0)
        self.assertIsNone(b["active"][0]["block_kind"])


class TestDiscovery(Base):
    def test_zero_byte_placeholder_skipped_and_names_unique(self):
        make_new_db(os.path.join(self.home, "kanban.db"),
                    [("a", "a", "done", None, None, None)])
        make_new_db(os.path.join(self.home, "kanban", "kanban.db"),
                    [("b", "b", "done", None, None, None)])
        os.makedirs(os.path.join(self.home, "kanban", "boards", "empty"))
        open(os.path.join(self.home, "kanban", "boards", "empty", "kanban.db"), "wb").close()
        doc = collector.collect(self.home)
        names = [b["name"] for b in doc["boards"]]
        self.assertEqual(names, ["kanban", "kanban-2"])
        self.assertTrue(all(b["ok"] for b in doc["boards"]))


class TestWalReadOnlyFallback(Base):
    def _wal_db(self):
        p = make_new_db(os.path.join(self.home, "kanban", "boards", "w", "kanban.db"),
                        [("r", "run", "running", 1700000000, None, None)])
        con = sqlite3.connect(p)
        con.execute("PRAGMA journal_mode=WAL")
        con.close()
        return p

    def _refusing_connect(self):
        real = sqlite3.connect
        calls = []

        def fake(database, *a, **kw):
            calls.append(database)
            if "immutable=1" not in database:
                raise sqlite3.OperationalError("unable to open database file")
            return real(database, *a, **kw)
        return fake, calls

    def test_cleanly_closed_wal_reopens_immutable_readonly(self):
        p = self._wal_db()
        self.assertFalse(os.path.exists(p + "-wal"))
        before = sorted(os.listdir(os.path.dirname(p)))
        mtime = os.stat(p).st_mtime_ns
        fake, calls = self._refusing_connect()
        with mock.patch.object(collector.sqlite3, "connect", fake):
            b = collector.collect(self.home)["boards"][0]
        self.assertTrue(b["ok"], b)
        self.assertEqual(b["status_counts"], {"running": 1})
        self.assertTrue(any("mode=ro&immutable=1" in u for u in calls))
        self.assertEqual(sorted(os.listdir(os.path.dirname(p))), before)
        self.assertEqual(os.stat(p).st_mtime_ns, mtime)

    def test_pending_wal_content_never_read_immutable(self):
        p = self._wal_db()
        with open(p + "-wal", "wb") as fh:
            fh.write(b"x" * 32)
        fake, calls = self._refusing_connect()
        with mock.patch.object(collector.sqlite3, "connect", fake):
            b = collector.collect(self.home)["boards"][0]
        self.assertFalse(b["ok"])
        self.assertEqual(b["error"], "io")
        self.assertFalse(any("immutable" in u for u in calls))


if __name__ == "__main__":
    unittest.main()
