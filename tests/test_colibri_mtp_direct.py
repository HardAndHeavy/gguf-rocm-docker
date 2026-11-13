"""CPU-only safety/configuration checks for the isolated issue-B runner."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json

SPEC = importlib.util.spec_from_file_location(
    'mtp_direct', Path(__file__).resolve().parents[1] / 'scripts/check-colibri-mtp-direct.py')
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class DirectRunnerTests(unittest.TestCase):
    def test_resolve_image_records_revision_and_pins_id(self):
        image_id = 'sha256:' + 'a' * 64
        info = [{'Id': image_id, 'Config': {'Labels': {'ru.hardandheavy.colibri.revision': 'test'}}, 'RepoDigests': []}]
        with patch.object(runner, 'cmd', return_value={'returncode': 0, 'stdout': json.dumps(info)}) as command:
            resolved, details = runner.resolve_image('test:tag')
        command.assert_called_once_with(['docker', 'image', 'inspect', 'test:tag'])
        self.assertEqual(resolved, image_id)
        self.assertEqual(details['labels']['ru.hardandheavy.colibri.revision'], 'test')
        self.assertEqual(details['requested_reference'], 'test:tag')

    def test_resolve_image_missing_fails_without_pull(self):
        with patch.object(runner, 'cmd', return_value={'returncode': 1}):
            with self.assertRaises(RuntimeError):
                runner.resolve_image('missing')

    def test_serialization_only_changes_two_environment_entries(self):
        for forced in (False, True):
            base = runner.case_environment('full', forced)
            serial = runner.case_environment('full-serialized', forced)
            self.assertEqual(serial, dict(base, AMD_SERIALIZE_KERNEL='3', AMD_SERIALIZE_COPY='3'))

    def test_forced_verify_is_explicit_not_baseline(self):
        base = runner.case_environment('full')
        self.assertEqual(base['Q38_MTP_DRAFTS'], '0')
        self.assertNotIn('Q38_MTP_PSTEP', base)
        self.assertNotIn('COLI_SPEC_GATE', base)
        self.assertEqual(runner.case_environment('full', True),
                         dict(base, Q38_MTP_DRAFTS='3', Q38_MTP_PSTEP='0', COLI_SPEC_GATE='0'))
        self.assertNotIn('COLI_CUDA_GEMV_SK', base)
        self.assertNotIn('COLI_CUDA_GEMV_W4', base)

    def test_case_environment_is_fresh_and_contains_no_api_secret(self):
        env = runner.case_environment('full')
        env['Q38_MTP'] = 'changed'
        self.assertEqual(runner.case_environment('full')['Q38_MTP'], '1')
        self.assertNotIn('COLI_API_KEY', env)

    def test_fault_status_is_not_missed(self):
        self.assertIsNotNone(runner.FAIL.search('Warning: Queue error - HSA_STATUS_ERROR_MEMORY_FAULT'))
        self.assertIsNone(runner.FAIL.search('[qtier] warm start completed'))

    def test_manifest_detects_content_changes_and_is_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / 'config.json'
            file.write_text('first')
            before = runner.manifest(root)
            self.assertEqual(before[0]['path'], 'config.json')
            self.assertEqual(before, runner.manifest(root))
            file.write_text('other')
            self.assertNotEqual(before, runner.manifest(root))


if __name__ == '__main__':
    unittest.main()
