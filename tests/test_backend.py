#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fixture-only tests for collector.py and poll.py.

No real local Hermes home and no real remote host is ever contacted: all
Hermes homes are tempfiles under TMPDIR, and every remote path is either
the disabled config or a mocked subprocess. Addresses used in tests are
RFC 5737 documentation ranges (192.0.2.0/24) or example.com — never real
private literals.

Run: python3 -m unittest discover -s tests -v
"""

import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import collector  # noqa: E402
import poll  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCHEMA = """
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    title TEXT,
    status TEXT,
    last_heartbeat_at INTEGER,
    started_at INTEGER
);
"""


def make_db(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO tasks(id,title,status,last_heartbeat_at,started_at)"
        " VALUES (?,?,?,?,?)",
        rows,
    )
    con.commit()
    con.close()
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="okb-", dir=os.environ.get("TMPDIR"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_config(self, doc):
        path = os.path.join(self.tmp, "config.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        return path


# ---------------------------------------------------------------------------
# collector
# ---------------------------------------------------------------------------

class TestCollector(Base):
    def test_missing_home_is_explicit_error(self):
        doc = collector.collect(os.path.join(self.tmp, "nope"))
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["boards"], [])
        self.assertEqual(doc["_meta"]["state"], "error")
        self.assertIn("hermes home not found", doc["_meta"]["detail"])

    def test_existing_empty_home_is_ok_empty(self):
        home = os.path.join(self.tmp, "home")
        os.makedirs(home)
        doc = collector.collect(home)
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["boards"], [])
        self.assertEqual(doc["_meta"]["state"], "ok")

    def test_discovery_counts_and_denominator(self):
        home = os.path.join(self.tmp, "home")
        make_db(os.path.join(home, "kanban", "boards", "alpha", "kanban.db"), [
            ("t1", "run me", "running", 1700000000, 1699999000),
            ("t2", "check me", "review", None, None),
            ("t3", "later", "ready", None, None),
            ("t4", "gone", "cancelled", None, None),
            ("t5", "shelved", "archived", None, None),
            ("t6", "odd", "weird-status", None, None),
        ])
        doc = collector.collect(home)
        self.assertTrue(doc["ok"])
        self.assertEqual(len(doc["boards"]), 1)
        b = doc["boards"][0]
        self.assertTrue(b["ok"])
        self.assertEqual(b["name"], "alpha")
        # unknown statuses counted; cancelled/archived excluded from total only
        self.assertEqual(b["status_counts"]["weird-status"], 1)
        self.assertEqual(b["status_counts"]["cancelled"], 1)
        self.assertEqual(b["total"], 4)  # running+review+ready+weird
        self.assertEqual([a["status"] for a in b["active"]],
                         ["running", "review", "ready"])
        self.assertEqual(b["last_heartbeat_at"], 1700000000)
        self.assertIsNone(b["active"][1]["heartbeat_at"])  # null-safe

    def test_active_priority_order(self):
        home = os.path.join(self.tmp, "home")
        make_db(os.path.join(home, "kanban.db"), [
            ("r1", "ready", "ready", 1700000500, None),
            ("b1", "blocked", "blocked", 1700000400, None),
            ("v1", "review", "review", 1700000300, None),
            ("n1", "running", "running", 1700000200, None),
        ])
        b = collector.collect(home)["boards"][0]
        self.assertEqual([a["status"] for a in b["active"]],
                         ["running", "review", "blocked", "ready"])

    def test_dedup_realpaths(self):
        home = os.path.join(self.tmp, "home")
        real = make_db(os.path.join(home, "kanban", "boards", "x", "kanban.db"),
                       [("t1", "a", "done", None, None)])
        link = os.path.join(home, "kanban.db")
        os.symlink(real, link)
        doc = collector.collect(home)
        self.assertEqual(len(doc["boards"]), 1)

    def test_unknown_schema_explicit(self):
        home = os.path.join(self.tmp, "home")
        p = os.path.join(home, "kanban.db")
        os.makedirs(home, exist_ok=True)
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE other(x)")
        con.commit()
        con.close()
        b = collector.collect(home)["boards"][0]
        self.assertFalse(b["ok"])
        self.assertEqual(b["error"], "schema")

    def test_not_a_database_explicit(self):
        home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(home, "kanban", "boards", "junk"))
        with open(os.path.join(home, "kanban", "boards", "junk", "kanban.db"),
                  "wb") as fh:
            fh.write(b"not a sqlite file at all")
        b = collector.collect(home)["boards"][0]
        self.assertFalse(b["ok"])
        self.assertIn(b["error"], ("schema", "io"))

    def test_read_only_no_writes(self):
        home = os.path.join(self.tmp, "home")
        p = make_db(os.path.join(home, "kanban", "boards", "ro", "kanban.db"),
                    [("t1", "a", "running", 1700000000, None)])
        mode_before = os.stat(p).st_mode
        mtime_before = os.stat(p).st_mtime_ns
        collector.collect(home)
        self.assertEqual(os.stat(p).st_mode, mode_before)
        self.assertEqual(os.stat(p).st_mtime_ns, mtime_before)
        self.assertEqual(sorted(os.listdir(home)), ["kanban"])

    def test_wal_database_readable_unmodified(self):
        home = os.path.join(self.tmp, "home")
        p = make_db(os.path.join(home, "kanban", "boards", "wal", "kanban.db"),
                    [("t1", "a", "done", None, None)])
        con = sqlite3.connect(p)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("INSERT INTO tasks VALUES('t2','b','running',1,NULL)")
        con.commit()
        con.close()
        b = collector.collect(home)["boards"][0]
        self.assertTrue(b["ok"])
        self.assertEqual(b["status_counts"], {"done": 1, "running": 1})
        con2 = sqlite3.connect(p)
        self.assertEqual(con2.execute("PRAGMA journal_mode").fetchone()[0],
                         "wal")
        con2.close()

    def test_partial_board_error_preserved(self):
        home = os.path.join(self.tmp, "home")
        make_db(os.path.join(home, "kanban", "boards", "good", "kanban.db"),
                [("t1", "a", "running", 1700000000, None)])
        bad = os.path.join(home, "kanban", "boards", "bad", "kanban.db")
        os.makedirs(os.path.dirname(bad))
        with open(bad, "wb") as fh:
            fh.write(b"junk")
        doc = collector.collect(home)
        self.assertTrue(doc["ok"])  # root ok survives a bad board
        good = [b for b in doc["boards"] if b["name"] == "good"][0]
        bad_b = [b for b in doc["boards"] if b["name"] == "bad"][0]
        self.assertTrue(good["ok"])
        self.assertFalse(bad_b["ok"])

    def test_malformed_values_do_not_crash(self):
        home = os.path.join(self.tmp, "home")
        p = os.path.join(home, "kanban.db")
        os.makedirs(home, exist_ok=True)
        con = sqlite3.connect(p)
        con.executescript(SCHEMA)
        con.execute("INSERT INTO tasks VALUES('t1','x','running','abc','zz')")
        con.commit()
        con.close()
        b = collector.collect(home)["boards"][0]
        self.assertTrue(b["ok"])
        self.assertEqual(b["active"][0]["heartbeat_at"], None)

    def test_no_percent_in_output(self):
        home = os.path.join(self.tmp, "home")
        make_db(os.path.join(home, "kanban.db"),
                [("t1", "a", "running", 1, 1)])
        out = json.dumps(collector.collect(home))
        self.assertNotIn("%", out)  # no fabricated percentage fields


# ---------------------------------------------------------------------------
# poll: config handling
# ---------------------------------------------------------------------------

class TestPollConfig(Base):
    def test_no_config_local_ok_remote_disabled(self):
        cfg = self.write_config({"local": {"hermesHome": self.tmp},
                                 "remote": {"enabled": False}})
        out = self.run_poll("--host", "mac", "--config", cfg)
        mac = out["hosts"]["mac"]
        self.assertFalse(mac["ok"])
        self.assertEqual(mac["boards"], [])
        self.assertEqual(mac["_meta"]["state"], "disabled")
        out = self.run_poll("--host", "pc", "--config", cfg)
        self.assertTrue(out["hosts"]["pc"]["ok"])

    def test_malformed_config(self):
        path = os.path.join(self.tmp, "config.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        out = self.run_poll("--host", "pc", "--config", path)
        pc = out["hosts"]["pc"]
        self.assertFalse(pc["ok"])
        self.assertEqual(pc["_meta"]["state"], "error")

    def test_config_sections_not_objects(self):
        cfg = self.write_config({"local": "oops"})
        out = self.run_poll("--host", "pc", "--config", cfg)
        self.assertEqual(out["hosts"]["pc"]["_meta"]["state"], "error")

    def run_poll(self, *args):
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "poll.py")] + list(args),
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "XDG_CONFIG_HOME": self.tmp})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# poll: host validation
# ---------------------------------------------------------------------------

class TestHostValidation(unittest.TestCase):
    def test_valid_hosts(self):
        for h in ("kanban-remote", "host.example.com", "myhost.local",
                  "user@host.example.com", "a1-b.example.org"):
            self.assertTrue(poll.is_valid_host(h), h)

    def test_malicious_hosts_rejected(self):
        bad = [
            "", "   ", "-oProxyCommand=evil", "--flag",
            "host;reboot", "host && id", "host|cmd", "$(id)", "`id`",
            "host\n-oProxyCommand=x", "host\rx", "host\tx", "a@b@example.com",
            "@host", "user@", "host/../ssh_config", "host:22", "host*",
            "host?q", "host!q", "host~q", "host'q", 'host"q', "host\\q",
            "192.0.2.1;id",  # RFC5737 example with injection
        ]
        for h in bad:
            self.assertFalse(poll.is_valid_host(h), repr(h))


# ---------------------------------------------------------------------------
# poll: remote (fully mocked subprocess)
# ---------------------------------------------------------------------------

class FakeProc:
    def __init__(self, rc=0, stdout="{}", stderr=""):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = stderr


class TestPollRemote(Base):
    def remote_cfg(self, **over):
        cfg = {"enabled": True, "host": "kanban-remote", "identityFile": "",
               "hostKeyAlias": "", "hermesHome": "~/.hermes"}
        cfg.update(over)
        return cfg

    def test_ssh_command_shape_and_spaces(self):
        ident = os.path.join(self.tmp, "my key with spaces")
        open(ident, "w").close()
        argv = poll.build_ssh_command(self.remote_cfg(identityFile="~/i d"))
        # identity path rides as its own argv element, never split
        self.assertEqual(argv[argv.index("-i") + 1], os.path.expanduser("~/i d"))
        self.assertIn("StrictHostKeyChecking=yes", argv)
        self.assertIn("BatchMode=yes", argv)
        self.assertIn("ConnectTimeout=5", argv)
        self.assertEqual(argv[-2:], ["python3", "-"])

    def test_bootstrap_end_to_end(self):
        # Run the exact payload ssh would pipe to `python3 -` locally.
        # Home contains a space and a quote; it does not exist, so the
        # collector must report the explicit missing-home error with the
        # path intact (proving safe transport, not shell mangling).
        code, sentinel = poll.encode_remote_bootstrap('~/h erm"x')
        proc = subprocess.run(
            [sys.executable, "-c", code, "--hermes-home", sentinel],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["_meta"]["state"], "error")
        self.assertIn('h erm"x', doc["_meta"]["detail"])

    def test_remote_timeout(self):
        def fake_run(*a, **k):
            raise subprocess.TimeoutExpired(cmd="ssh", timeout=20)
        orig = subprocess.run
        subprocess.run = fake_run
        try:
            doc = poll.collect_remote(self.remote_cfg())
        finally:
            subprocess.run = orig
        self.assertEqual(doc["_meta"]["state"], "offline")
        self.assertIn("timeout", doc["_meta"]["detail"])

    def test_remote_process_error(self):
        orig = subprocess.run
        subprocess.run = lambda *a, **k: FakeProc(rc=255, stderr="refused")
        try:
            doc = poll.collect_remote(self.remote_cfg())
        finally:
            subprocess.run = orig
        self.assertEqual(doc["_meta"]["state"], "offline")
        self.assertIn("rc=255", doc["_meta"]["detail"])

    def test_remote_invalid_json(self):
        orig = subprocess.run
        subprocess.run = lambda *a, **k: FakeProc(stdout="not json")
        try:
            doc = poll.collect_remote(self.remote_cfg())
        finally:
            subprocess.run = orig
        self.assertEqual(doc["_meta"]["state"], "error")

    def test_remote_ssh_missing(self):
        def fake_run(*a, **k):
            raise FileNotFoundError("ssh")
        orig = subprocess.run
        subprocess.run = fake_run
        try:
            doc = poll.collect_remote(self.remote_cfg())
        finally:
            subprocess.run = orig
        self.assertEqual(doc["_meta"]["state"], "offline")

    def test_remote_uses_ssh_not_shell(self):
        captured = {}

        def fake_run(argv, **k):
            captured["argv"] = argv
            captured["input"] = k.get("input")
            return FakeProc(stdout=json.dumps({"ok": True, "boards": []}))

        orig = subprocess.run
        subprocess.run = fake_run
        try:
            doc = poll.collect_remote(self.remote_cfg())
        finally:
            subprocess.run = orig
        self.assertEqual(captured["argv"][0], "ssh")
        self.assertIsInstance(captured["argv"], list)  # argv array, no shell
        self.assertIn("--hermes-home", captured["argv"])
        self.assertIn("collector", captured["input"])


# ---------------------------------------------------------------------------
# static hygiene scan of committed backend files
# ---------------------------------------------------------------------------

class TestStaticHygiene(unittest.TestCase):
    FILES = [os.path.join(ROOT, "poll.py"), os.path.join(ROOT, "collector.py"),
             os.path.join(ROOT, "config.example.json")]

    def test_no_private_literals(self):
        # real private IPv4 ranges (not RFC5737), personal usernames, key paths
        banned = [
            r"192\.168\.", r"10\.\d+\.\d+\.\d+", r"172\.(1[6-9]|2\d|3[01])\.",
            r"/Users/[A-Za-z]", r"/home/[A-Za-z]",
            r"hendkai@(?!example)", r"_macmini", r"100\.\d+\.\d+\.\d+",
        ]
        for path in self.FILES:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for pat in banned:
                self.assertIsNone(re.search(pat, text),
                                  "%s matches %s" % (path, pat))

    def test_example_config_generic(self):
        with open(os.path.join(ROOT, "config.example.json"),
                  encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["remote"]["enabled"], False)
        self.assertEqual(doc["remote"]["host"], "kanban-remote")
        self.assertEqual(doc["local"]["hermesHome"], "~/.hermes")


if __name__ == "__main__":
    unittest.main()
