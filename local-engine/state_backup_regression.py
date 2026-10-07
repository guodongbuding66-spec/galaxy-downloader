"""Failure-injection tests run from both source and the shipped state tool."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import state_backup as backup


class BackupRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'
        self.state.mkdir()
        self.context = SimpleNamespace(app_dir=lambda: self.root, state_dir=lambda: self.state)
        self.path = self.root / 'backup.zip'
        self.original = b'{"historyEnabled":true}'
        (self.state / 'workspace-options.json').write_bytes(self.original)
        (self.state / 'download-profiles.json').write_bytes(b'{"version":1,"profiles":[]}')
        backup.create_state_backup(self.context, self.path)

    def files(self):
        return {p.name: p.read_bytes() for p in self.state.iterdir() if p.is_file()}

    def rewrite(self, edit):
        with zipfile.ZipFile(self.path) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        edit(entries)
        with zipfile.ZipFile(self.path, 'w') as archive:
            for name, content in entries.items():
                archive.writestr(name, content)

    def reject_without_changes(self):
        before = self.files()
        with self.assertRaises(backup.StateBackupError):
            backup.restore_state_backup(self.context, self.path)
        self.assertEqual(before, self.files())

    def test_tampered_checksum(self):
        self.rewrite(lambda entries: entries.update({'state/workspace-options.json': b'{"historyEnabled":nooo}'}))
        self.reject_without_changes()

    def test_duplicate_member(self):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(self.path, 'a') as archive:
                archive.writestr('manifest.json', '{}')
        self.reject_without_changes()

    def test_path_traversal(self):
        self.rewrite(lambda entries: entries.update({'state/../../outside.txt': b'bad'}))
        self.reject_without_changes()
        self.assertFalse((self.root.parent / 'outside.txt').exists())

    def test_missing_member(self):
        self.rewrite(lambda entries: entries.pop('state/workspace-options.json'))
        self.reject_without_changes()

    def test_unsupported_schema(self):
        def edit(entries):
            manifest = json.loads(entries['manifest.json'])
            manifest['schema'] = 'future/v999'
            entries['manifest.json'] = json.dumps(manifest)
        self.rewrite(edit)
        self.reject_without_changes()

    def test_crc_corruption(self):
        self.rewrite(lambda entries: None)
        with zipfile.ZipFile(self.path) as archive:
            info = archive.getinfo('state/workspace-options.json')
            offset = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
        data = bytearray(self.path.read_bytes())
        data[offset] ^= 1
        self.path.write_bytes(data)
        self.reject_without_changes()

    def test_truncated_archive(self):
        self.path.write_bytes(self.path.read_bytes()[:40])
        self.reject_without_changes()

    def test_manifest_limit(self):
        with patch.object(backup, 'MAX_MANIFEST_BYTES', 8):
            self.reject_without_changes()

    def test_backup_cannot_overwrite_state(self):
        before = self.files()
        with self.assertRaises(backup.StateBackupError):
            backup.create_state_backup(self.context, self.state / 'workspace-options.json')
        self.assertEqual(before, self.files())

    def test_failed_backup_preserves_existing_archive(self):
        before = self.path.read_bytes()
        with patch.object(backup, '_snapshot', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                backup.create_state_backup(self.context, self.path)
        self.assertEqual(before, self.path.read_bytes())
        self.assertFalse(list(self.root.glob('.*.tmp')))

    def test_restore_failure_rolls_back_only_touched_files(self):
        (self.state / 'workspace-options.json').write_bytes(b'{"historyEnabled":false}')
        (self.state / 'desktop-features.json').write_bytes(b'{"clipboardMonitorEnabled":true}')
        before = self.files()
        replace = os.replace
        def fail_second(source, target):
            if Path(source).parent.name == 'stage' and Path(target).name == 'download-profiles.json':
                raise PermissionError('locked file')
            return replace(source, target)
        with patch.object(backup.os, 'replace', side_effect=fail_second):
            with self.assertRaisesRegex(backup.StateBackupError, 'previous state was restored'):
                backup.restore_state_backup(self.context, self.path)
        self.assertEqual(before, self.files())

    def test_rollback_failure_retains_recovery(self):
        (self.state / 'workspace-options.json').write_bytes(b'{"historyEnabled":false}')
        replace = os.replace
        def fail(source, target):
            if Path(source).parent.name == 'rollback':
                raise PermissionError('rollback locked')
            if Path(source).parent.name == 'stage' and Path(target).name == 'download-profiles.json':
                raise PermissionError('restore locked')
            return replace(source, target)
        with patch.object(backup.os, 'replace', side_effect=fail):
            with self.assertRaisesRegex(backup.StateBackupError, 'Recovery copies retained'):
                backup.restore_state_backup(self.context, self.path)
        recovery = list(self.root.glob('galaxy-state-recovery-*'))
        self.assertEqual(len(recovery), 1)
        self.assertEqual((recovery[0] / 'workspace-options.json').read_bytes(), b'{"historyEnabled":false}')

    def test_sqlite_wal_snapshot(self):
        db_path = self.state / 'media-library.sqlite3'
        with sqlite3.connect(db_path) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA wal_autocheckpoint=0')
            db.execute('CREATE TABLE item(value TEXT)')
            db.execute("INSERT INTO item VALUES ('committed-wal')")
            db.commit()
            backup.create_state_backup(self.context, self.path)
        db.close()
        backup.restore_state_backup(self.context, self.path)
        self.assertEqual(backup._sqlite_scalar(db_path, 'SELECT value FROM item'), 'committed-wal')
        self.assertFalse(Path(str(db_path) + '-wal').exists())

    def test_sqlite_sidecars_removed(self):
        for suffix in ('-wal', '-shm', '-journal'):
            (self.state / ('media-library.sqlite3' + suffix)).write_bytes(b'stale')
        backup.restore_state_backup(self.context, self.path)
        self.assertFalse(list(self.state.glob('media-library.sqlite3-*')))

    def test_invalid_sqlite_with_valid_checksum(self):
        content = b'not a sqlite database'
        def edit(entries):
            manifest = json.loads(entries['manifest.json'])
            manifest['files'].append({'name': 'media-library.sqlite3', 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
            entries['manifest.json'] = json.dumps(manifest)
            entries['state/media-library.sqlite3'] = content
        self.rewrite(edit)
        self.reject_without_changes()

    def test_actual_extra_state_sources_roundtrip(self):
        for name in ('media-options.json', 'bandwidth-options.json'):
            (self.state / name).write_bytes(b'{"configured":true}')
        gallery = self.state / 'gallery-dl'
        gallery.mkdir()
        database = gallery / 'archive.sqlite3'
        backup._sqlite_exec(database, ['CREATE TABLE seen(id TEXT)', "INSERT INTO seen VALUES ('media-1')"])
        backup.create_state_backup(self.context, self.path)
        (self.state / 'media-options.json').unlink()
        (self.state / 'bandwidth-options.json').write_bytes(b'{}')
        database.unlink()
        gallery.rmdir()
        backup.restore_state_backup(self.context, self.path)
        self.assertEqual((self.state / 'media-options.json').read_bytes(), b'{"configured":true}')
        self.assertEqual((self.state / 'bandwidth-options.json').read_bytes(), b'{"configured":true}')
        self.assertEqual(backup._sqlite_scalar(database, 'SELECT id FROM seen'), 'media-1')

    def test_nested_symlink_directory_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        try:
            (self.state / 'gallery-dl').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('OS does not permit symlink creation')
        with self.assertRaises(backup.StateBackupError):
            backup.create_state_backup(self.context, self.path)
        with self.assertRaises(backup.StateBackupError):
            backup.restore_state_backup(self.context, self.path)
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlink_not_replaced(self):
        outside = self.root / 'outside.json'
        outside.write_bytes(b'outside')
        target = self.state / 'workspace-options.json'
        target.unlink()
        try:
            target.symlink_to(outside)
        except OSError:
            self.skipTest('OS does not permit symlink creation')
        self.reject_without_changes()
        self.assertTrue(target.is_symlink())
        self.assertEqual(outside.read_bytes(), b'outside')


def run_state_backup_regression():
    result = unittest.TestResult()
    unittest.defaultTestLoader.loadTestsFromTestCase(BackupRegression).run(result)
    if not result.wasSuccessful():
        failures = '\n'.join(error for _, error in result.errors + result.failures)
        raise AssertionError(f'Backup/Restore regression failed:\n{failures}')
    return {'tests': result.testsRun, 'skipped': len(result.skipped), 'ok': True}


if __name__ == '__main__':
    print(json.dumps(run_state_backup_regression()))
