import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('archive_source', Path(__file__).parents[1] / 'scripts/archive_source.py')
archive_source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive_source)


class ArchiveValidationTests(unittest.TestCase):
    def test_rejects_release_path_traversal(self):
        with self.assertRaises(ValueError):
            archive_source.prepare(Path('/source'), Path('/output'), '../1.5.3')

    def test_rejects_relative_paths(self):
        with self.assertRaises(ValueError):
            archive_source.prepare(Path('source'), Path('/output'), '1.5.3')


if __name__ == '__main__':
    unittest.main()
