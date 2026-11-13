import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('fetch_git', Path(__file__).parents[1] / 'scripts/fetch_pub_git.py')
fetch_git = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_git)


class PubGitTests(unittest.TestCase):
    def test_lockfile_rejects_untrusted_git_url(self):
        data = '''packages:
  example:
    source: git
    description:
      url: https://example.invalid/example/project
      resolved-ref: ''' + 'a' * 40 + '\n'
        with self.assertRaises(ValueError):
            fetch_git.records(io.StringIO(data))

    def test_existing_partial_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            commit = 'a' * 40
            partial = cache / f'example-{commit}.git.part'
            partial.mkdir()
            (partial / 'owned').write_text('other process')
            with self.assertRaises(FileExistsError):
                fetch_git.fetch(cache, ('example', 'https://github.com/example/project', commit))
            self.assertEqual((partial / 'owned').read_text(), 'other process')


if __name__ == '__main__':
    unittest.main()
