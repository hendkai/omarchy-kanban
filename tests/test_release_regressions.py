"""Independent regression checks; fixtures only, no live homes or network."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import collector
import poll


class ReleaseRegressionTests(unittest.TestCase):
    def test_explicit_wal_snapshot_survives_new_commit(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'board.db'
            writer = sqlite3.connect(p)
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('CREATE TABLE sample(x)')
            writer.execute('INSERT INTO sample VALUES (1)')
            writer.commit()
            reader = collector.open_ro(str(p))
            try:
                self.assertTrue(reader.in_transaction)
                self.assertEqual(reader.execute('SELECT count(*) FROM sample').fetchone()[0], 1)
                writer.execute('INSERT INTO sample VALUES (2)')
                writer.commit()
                self.assertEqual(reader.execute('SELECT count(*) FROM sample').fetchone()[0], 1)
                with self.assertRaises(sqlite3.OperationalError):
                    reader.execute('DELETE FROM sample')
            finally:
                reader.close()
                writer.close()

    def test_missing_id_is_schema_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'kanban.db'
            with sqlite3.connect(p) as db:
                db.execute('CREATE TABLE tasks(title,status,last_heartbeat_at,started_at)')
            self.assertEqual(collector.collect(d)['boards'][0]['error'], 'schema')

    def test_environment_home_and_independent_local_config(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'HERMES_HOME': d}):
            self.assertTrue(poll.host_document({'remote': 'invalid'}, 'pc')['ok'])
            self.assertTrue(poll.host_document({}, 'pc')['ok'])

    def test_no_network_without_literal_boolean_opt_in(self):
        with patch('poll.subprocess.run') as run:
            for enabled in [False, 'false', 'true', 1, None, []]:
                result = poll.host_document({'remote': {'enabled': enabled, 'host': 'example.com'}}, 'mac')
                self.assertFalse(result['ok'])
            run.assert_not_called()

    def test_malformed_remote_metadata_is_error(self):
        remote = {'host': 'example.com', 'hermesHome': '~/.hermes'}
        for output in [{'ok': True, 'boards': [], '_meta': None}, {'ok': 'yes', 'boards': []}, {'ok': True, 'boards': {}}]:
            completed = subprocess.CompletedProcess([], 0, json.dumps(output), '')
            with patch('poll.subprocess.run', return_value=completed):
                self.assertEqual(poll.collect_remote(remote)['_meta']['state'], 'error')

    def test_discovery_permission_failure_is_not_empty(self):
        with tempfile.TemporaryDirectory() as d, patch('collector.discover_board_dbs', side_effect=PermissionError('denied')):
            result = collector.collect(d)
            self.assertFalse(result['ok'])
            self.assertEqual(result['_meta']['state'], 'error')

    def test_collection_global_deadline(self):
        with tempfile.TemporaryDirectory() as d, patch('collector.discover_board_dbs', return_value=[('x','unused')]), patch('collector.time.monotonic', side_effect=[0.0,11.0]), patch('collector.collect_board') as read:
            result = collector.collect(d)
            self.assertFalse(result['ok'])
            read.assert_not_called()
