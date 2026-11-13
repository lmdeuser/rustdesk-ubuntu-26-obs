import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('fetch_pub', Path(__file__).parents[1] / 'scripts/fetch_pub_archives.py')
fetch_pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_pub)


class PubArchiveTests(unittest.TestCase):
    def test_lockfile_rejects_non_pub_registry(self):
        data = '''packages:
  example:
    source: hosted
    version: 1.2.3
    description:
      name: example
      url: https://example.invalid
      sha256: ''' + 'a' * 64 + '\n'
        with self.assertRaises(ValueError):
            fetch_pub.package_records(io.StringIO(data))

    def test_existing_partial_file_is_not_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            partial = cache / 'example-1.2.3.tar.gz.part'
            partial.write_text('owned by another process')
            with self.assertRaises(FileExistsError):
                fetch_pub.download(cache, ('example', '1.2.3', 'a' * 64))
            self.assertEqual(partial.read_text(), 'owned by another process')

    def test_existing_archive_must_match(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            archive = cache / 'example-1.2.3.tar.gz'
            archive.write_bytes(b'example')
            fetch_pub.download(cache, ('example', '1.2.3', hashlib.sha256(b'example').hexdigest()))
            with self.assertRaises(ValueError):
                fetch_pub.download(cache, ('example', '1.2.3', 'a' * 64))
            self.assertEqual(archive.read_bytes(), b'example')


if __name__ == '__main__':
    unittest.main()
