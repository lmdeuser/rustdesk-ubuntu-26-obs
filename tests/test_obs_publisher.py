import gzip
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('obs_publisher', Path(__file__).parents[1] / 'scripts/obs_publisher.py')
obs_publisher = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = obs_publisher
spec.loader.exec_module(obs_publisher)


class ObsPublisherTests(unittest.TestCase):
    def test_version_normalization_and_comparison(self):
        self.assertEqual(obs_publisher.normalize_upstream_version('v1.5.3'), '1.5.3')
        self.assertEqual(obs_publisher.base_version_from_debian('1.5.3-0ubuntu1~obs1'), '1.5.3')
        self.assertEqual(obs_publisher.compare_versions('1.5.10', '1.5.3'), 1)
        self.assertEqual(obs_publisher.compare_versions('1.5.3', '1.5.3'), 0)
        with self.assertRaises(ValueError):
            obs_publisher.normalize_upstream_version('1.5.3-nightly')

    def test_parse_apt_packages_version(self):
        index = (
            'Package: other\nVersion: 9.9.9\n\n'
            'Package: rustdesk\nVersion: 1.5.2-0ubuntu1~obs1\n\n'
            'Package: rustdesk\nVersion: 1.5.3-0ubuntu1~obs1\n\n'
        )
        self.assertEqual(obs_publisher.parse_apt_packages_version(index), '1.5.3-0ubuntu1~obs1')
        self.assertIsNone(obs_publisher.parse_apt_packages_version(index, package='missing'))

    def test_parse_osc_results_xml(self):
        xml = (
            '<resultlist state="abc">'
            '  <result project="home:dwolfF:rustdesk:staging" repository="xUbuntu_26.04" arch="x86_64" code="building" state="building">'
            '    <status package="rustdesk" code="succeeded" />'
            '  </result>'
            '</resultlist>'
        )
        self.assertEqual(
            obs_publisher.parse_osc_results_xml(xml, 'xUbuntu_26.04', 'x86_64', 'rustdesk'),
            'succeeded',
        )
        self.assertEqual(
            obs_publisher.parse_osc_results_xml(xml, 'Ubuntu_24.04', 'x86_64', 'rustdesk'),
            'unknown',
        )
        dirty_xml = (
            '<resultlist><result repository="xUbuntu_26.04" arch="x86_64" dirty="true">'
            '<status package="rustdesk" code="broken"/></result></resultlist>'
        )
        self.assertEqual(
            obs_publisher.parse_osc_results_xml(dirty_xml, 'xUbuntu_26.04', 'x86_64', 'rustdesk'),
            'building',
        )

    def test_verify_apt_endpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            cfg = obs_publisher.PublisherConfig(repo_root=Path(temporary), work_root=Path(temporary))
            pkg_gz = gzip.compress(b'Package: rustdesk\nVersion: 1.5.3-0ubuntu1~obs1\n\n')
            blobs = {
                f'{cfg.apt_base_url}/Release': b'Origin: OBS\nSuites: /\n',
                f'{cfg.apt_base_url}/Release.key': b'-----BEGIN PGP PUBLIC KEY BLOCK-----\nabc\n-----END PGP PUBLIC KEY BLOCK-----\n',
                f'{cfg.apt_base_url}/Packages.gz': pkg_gz,
            }
            info = obs_publisher.verify_apt_endpoint(
                cfg,
                expected_version='1.5.3-0ubuntu1~obs1',
                fetch=lambda url: blobs[url],
            )
            self.assertEqual(info, {'apt_version': '1.5.3-0ubuntu1~obs1'})

    def test_ensure_changelog_version_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            cl = Path(temporary) / 'changelog'
            cl.write_text('rustdesk (1.5.2-0ubuntu1~obs1) resolute; urgency=medium\n\n  * Old.\n\n -- Maintainer <noreply@github.com>  Sat, 14 Nov 2026 00:00:00 +0000\n')
            changed = obs_publisher.ensure_changelog_version(cl, '1.5.3-0ubuntu1~obs1', 'Maintainer <noreply@github.com>')
            self.assertTrue(changed)
            changed_again = obs_publisher.ensure_changelog_version(cl, '1.5.3-0ubuntu1~obs1', 'Maintainer <noreply@github.com>')
            self.assertFalse(changed_again)

    def test_wait_for_obs_build_raises_on_failed(self):
        with tempfile.TemporaryDirectory() as temporary:
            cfg = obs_publisher.PublisherConfig(repo_root=Path(temporary), work_root=Path(temporary))

            def fake_run(cmd, **kwargs):
                if 'results' in cmd:
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        stdout='<resultlist><result repository="xUbuntu_26.04" arch="x86_64"><status package="rustdesk" code="failed"/></result></resultlist>',
                    )
                return subprocess.CompletedProcess(cmd, 0, stdout='compile error line 1\ncompile error line 2\n')

            with self.assertRaises(RuntimeError) as ctx:
                obs_publisher.wait_for_obs_build(cfg, run_cmd=fake_run, sleep_fn=lambda _: None)
            self.assertIn('compile error line 2', str(ctx.exception))

    def test_build_dsc_text_and_control_parsing(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp = Path(temporary)
            ctrl = tmp / 'control'
            ctrl.write_text(
                'Source: rustdesk\nSection: net\nPriority: optional\n'
                'Maintainer: RustDesk Packaging <noreply@github.com>\n'
                'Build-Depends: debhelper-compat (= 13),\n pkgconf\n\n'
                'Package: rustdesk\nArchitecture: amd64\nDepends: ${shlibs:Depends}\nDescription: test\n',
                encoding='utf-8',
            )
            archive = tmp / 'rustdesk_1.5.3.orig.tar.gz'
            archive.write_bytes(b'test-archive-bytes')
            dsc = obs_publisher.build_dsc_text(ctrl, '1.5.3-0ubuntu1~obs1', [archive])
            self.assertIn('Format: 3.0 (quilt)', dsc)
            self.assertIn('Build-Depends: debhelper-compat (= 13), pkgconf', dsc)
            self.assertIn('rustdesk_1.5.3.orig.tar.gz', dsc)
            self.assertIn('Checksums-Sha256:', dsc)

    def test_sync_obs_staging_prunes_and_commits(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp = Path(temporary)
            cfg = obs_publisher.PublisherConfig(repo_root=tmp, work_root=tmp)
            rel = tmp / 'releases/1.5.3'
            rel.mkdir(parents=True)
            names = [
                'rustdesk_1.5.3.orig.tar.gz',
                'rustdesk_1.5.3.orig-sdk.tar.xz',
                'rustdesk_1.5.3.orig-pubcache.tar.xz',
                'rustdesk_1.5.3.orig-vendor.tar.xz',
                'rustdesk_1.5.3-0ubuntu1~obs1.debian.tar.xz',
                'rustdesk_1.5.3-0ubuntu1~obs1.dsc',
            ]
            for name in names:
                (rel / name).write_text(name)
            pkg_co = tmp / 'obs-checkout' / cfg.staging_project / cfg.package
            (pkg_co / '.osc').mkdir(parents=True)
            (pkg_co / 'rustdesk_1.5.2.orig.tar.gz').write_text('stale')
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 0, stdout='')

            obs_publisher.sync_obs_staging(cfg, rel, '1.5.3-0ubuntu1~obs1', run_cmd=fake_run)
            self.assertFalse((pkg_co / 'rustdesk_1.5.2.orig.tar.gz').exists())
            self.assertTrue((pkg_co / 'rustdesk_1.5.3-0ubuntu1~obs1.dsc').exists())
            self.assertIn(['osc', '-A', cfg.obs_api, 'addremove'], calls)

    def test_promote_to_production_passes_repo_and_no_delay(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp = Path(temporary)
            cfg = obs_publisher.PublisherConfig(repo_root=tmp, work_root=tmp)
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append((cmd, kwargs))
                return subprocess.CompletedProcess(cmd, 0, stdout='')

            obs_publisher.promote_to_production(cfg, run_cmd=fake_run)
            self.assertEqual(
                calls,
                [(
                    [
                        'osc', '-A', cfg.obs_api, 'release',
                        '-r', cfg.repository,
                        '--target-project', cfg.production_project,
                        '--target-repository', cfg.repository,
                        '--no-delay',
                        cfg.staging_project,
                        cfg.package,
                    ],
                    {'check': True},
                )],
            )


if __name__ == '__main__':
    unittest.main()
