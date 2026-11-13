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

    def test_rejects_relative_root(self):
        with self.assertRaises(ValueError):
            retention.prune(Path('.'))


if __name__ == '__main__':
    unittest.main()
