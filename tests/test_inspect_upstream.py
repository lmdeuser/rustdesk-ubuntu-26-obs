import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('inspect_upstream', Path(__file__).parents[1] / 'scripts/inspect_upstream.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class InspectTests(unittest.TestCase):
    def test_features_are_read_from_release_manifest(self):
        def fetch(url):
            if url == module.API:
                return json.dumps({'tag_name': '1.2.3', 'html_url': 'https://example.invalid/release'}).encode()
            self.assertEqual(url, module.RAW.format('1.2.3'))
            return b'[features]\nhwcodec = []\n[dependencies]\nscrap = { path = "libs/scrap", features = ["wayland"] }\n'
        result = module.inspect(fetch)
        self.assertEqual(result['cargo_features'], {'wayland': False, 'hwcodec': True})
        self.assertTrue(result['scrap_wayland_enabled'])

    def test_rejects_path_in_tag(self):
        def fetch(_url):
            return b'{"tag_name":"../main","html_url":"https://example.invalid"}'
        with self.assertRaises(ValueError):
            module.inspect(fetch)


if __name__ == '__main__':
    unittest.main()
