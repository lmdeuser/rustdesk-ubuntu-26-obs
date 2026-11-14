import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('retention', Path(__file__).parents[1] / 'scripts/retention.py')
retention = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retention)


class RetentionTests(unittest.TestCase):
    def test_dry_run_then_remove_only_old_marked_sets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for version in ('1.2.9', '1.2.10', '2.0.0'):
                folder = root / version
                folder.mkdir()
                (folder / '.rustdesk-source-set').write_text(retention.MARKER)
            unmarked = root / '0.1.0'
            unmarked.mkdir()
            (root / '0.2.0').symlink_to(unmarked, target_is_directory=True)
            self.assertEqual([p.name for p in retention.prune(root)], ['1.2.9'])
            self.assertTrue((root / '1.2.9').exists())
            retention.prune(root, apply=True)
            self.assertFalse((root / '1.2.9').exists())
            self.assertTrue(unmarked.exists())
            self.assertTrue((root / '0.2.0').is_symlink())
            self.assertEqual(retention.prune(root, apply=True), [])

    def test_protected_version_is_never_pruned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for version in ('1.5.1', '1.5.2', '1.5.3'):
                folder = root / version
                folder.mkdir()
                (folder / '.rustdesk-source-set').write_text(retention.MARKER)
            removed = retention.prune(root, apply=True, keep=1, protect=('1.5.1',))
            self.assertEqual([p.name for p in removed], ['1.5.2'])
            self.assertTrue((root / '1.5.1').exists())
            self.assertTrue((root / '1.5.3').exists())

    def test_prune_obs_package_files_keeps_active_set(self):
        with tempfile.TemporaryDirectory() as temporary:
            co = Path(temporary)
            (co / '.osc').mkdir()
            active = ['rustdesk_1.5.3.orig.tar.gz', 'rustdesk_1.5.3-0ubuntu1~obs1.dsc']
            stale = ['rustdesk_1.5.2.orig.tar.gz', 'rustdesk_1.5.2-0ubuntu1~obs1.dsc']
            for name in active + stale + ['README.local']:
                (co / name).write_text('x')
            removed = retention.prune_obs_package_files(co, active, apply=True)
            self.assertEqual(sorted(p.name for p in removed), sorted(stale))
            self.assertTrue((co / 'README.local').exists())
            self.assertTrue((co / 'rustdesk_1.5.3.orig.tar.gz').exists())

    def test_rejects_relative_root(self):
        with self.assertRaises(ValueError):
            retention.prune(Path('.'))


if __name__ == '__main__':
    unittest.main()
