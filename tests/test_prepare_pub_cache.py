import io
import sys
import tarfile
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import prepare_pub_cache


class PubCacheTests(unittest.TestCase):
    def test_rejects_traversal_before_extracting(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'unsafe.tar.gz'
            destination = root / 'destination'
            destination.mkdir()
            with tarfile.open(archive, 'w:gz') as tar:
                entry = tarfile.TarInfo('../escaped')
                entry.size = 1
                tar.addfile(entry, io.BytesIO(b'x'))
            with self.assertRaises(ValueError):
                prepare_pub_cache.unpack(archive, destination)
            self.assertFalse((root / 'escaped').exists())

    def test_rejects_symlink_member(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'unsafe.tar.gz'
            destination = root / 'destination'
            destination.mkdir()
            with tarfile.open(archive, 'w:gz') as tar:
                entry = tarfile.TarInfo('link')
                entry.type = tarfile.SYMTYPE
                entry.linkname = 'target'
                tar.addfile(entry)
            with self.assertRaises(ValueError):
                prepare_pub_cache.unpack(archive, destination)
            self.assertFalse((destination / 'link').exists())


if __name__ == '__main__':
    unittest.main()
