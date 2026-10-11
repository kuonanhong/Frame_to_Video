"""Download-fix regressions: Linux-hosted mocks are not physical Intel Mac tests.

No model weights, package installs, git calls, or network access occur here.
"""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import download_support
import install
import registry
import server

MODERN = ('liveportrait', 'flux-klein', 'ltx-video', 'cogvideox')


class DownloadFixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.runtime_patch = patch.object(registry, 'RUNTIME', self.root)
        self.runtime_patch.start()
        self.installer_runtime_patch = patch.object(install, 'RUNTIME', self.root)
        self.installer_runtime_patch.start()

    def tearDown(self):
        self.installer_runtime_patch.stop()
        self.runtime_patch.stop()
        self.temp.cleanup()

    def cli(self, expert, *arguments, system='Darwin', machine='x86_64'):
        """Exercise actual routing; intercept every package/worker subprocess."""
        calls, creations = [], []

        def run(command, **kwargs):
            command = list(map(str, command))
            calls.append(command)
            output = json.dumps({'ready': True, 'versions': {}, 'missing': []})
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr='')

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, 'argv', ['install.py', expert, *arguments]))
            stack.enter_context(patch.object(install.platform, 'system', return_value=system))
            stack.enter_context(patch.object(install.platform, 'machine', return_value=machine))
            stack.enter_context(patch.object(install.venv.EnvBuilder, 'create', side_effect=lambda path: creations.append(Path(path))))
            stack.enter_context(patch.object(install.subprocess, 'run', side_effect=run))
            stack.enter_context(patch.object(install.subprocess, 'check_output', return_value=''))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            install.main()
        return calls, creations

    def assert_weights_only(self, expert, calls, creations):
        self.assertTrue(calls, 'A downloader command should be launched')
        self.assertFalse(any('worker.py' in Path(arg).name for cmd in calls for arg in cmd),
                         'Weights-only mode must not run inference dependency checks')
        self.assertFalse(any(arg.startswith(('torch==', 'torchvision==')) for cmd in calls for arg in cmd))
        runtime_requirements = {'modern.txt', 'liveportrait.txt', 'diffusion.txt', 'qwen.txt'}
        self.assertFalse(any(Path(arg).name in runtime_requirements for cmd in calls for arg in cmd),
                         'Weights-only mode must not install runtime requirements')
        self.assertNotIn(self.root / expert / 'venv', creations)

    def test_four_original_intel_download_commands_use_no_torch(self):
        for expert in MODERN:
            with self.subTest(expert=expert):
                calls, creations = self.cli(expert, '--download')
                self.assert_weights_only(expert, calls, creations)

    def test_explicit_weights_only_works_on_supported_host(self):
        calls, creations = self.cli('ltx-video', '--weights-only', system='Linux')
        self.assert_weights_only('ltx-video', calls, creations)

    def test_old_profile_retains_runtime_install(self):
        calls, creations = self.cli('controlnet-canny', '--download', system='Linux')
        self.assertIn(self.root / 'controlnet-canny' / 'venv', creations)
        self.assertTrue(any('torch==2.2.2' in cmd for cmd in calls))
        self.assertTrue(any(any(Path(arg).name == 'diffusion.txt' for arg in cmd) for cmd in calls))
        self.assertTrue(any('--check' in cmd for cmd in calls))

    def manifest(self, expert='ltx-video', content=b'fixed model bytes'):
        home = self.root / expert
        model = home / 'models' / 'model' / 'transformer' / 'diffusion_pytorch_model.safetensors'
        model.parent.mkdir(parents=True)
        model.write_bytes(content)
        manifest = {'schema': 2, 'expert': expert, 'install_mode': 'weights-only',
                    'models': [{'name': 'model', 'repo': registry.EXPERTS[expert]['repos'][0]['repo'],
                                'revision': '1' * 40}],
                    'files': [{'path': str(model.relative_to(home)), 'bytes': len(content),
                               'sha256': hashlib.sha256(content).hexdigest()}]}
        (home / 'install-manifest.json').write_text(json.dumps(manifest))
        return home, model, manifest

    def test_verify_hashes_offline_and_detects_same_size_corruption(self):
        home, model, manifest = self.manifest()
        with patch.object(install.subprocess, 'run', side_effect=AssertionError('Unexpected process')), \
             contextlib.redirect_stdout(io.StringIO()):
            install.verify('ltx-video')
            model.write_bytes(b'X' * model.stat().st_size)
            with self.assertRaises((RuntimeError, ValueError)):
                install.verify('ltx-video')

    def test_verify_rejects_manifest_path_escape(self):
        home, model, manifest = self.manifest()
        outside = self.root / 'outside.bin'
        outside.write_bytes(model.read_bytes())
        manifest['files'][0]['path'] = '../outside.bin'
        (home / 'install-manifest.json').write_text(json.dumps(manifest))
        with self.assertRaises((RuntimeError, ValueError)):
            install.verify('ltx-video')

    def test_downloaded_weights_are_not_reported_runnable(self):
        self.manifest()
        with patch.object(server, 'memory_check', return_value={'ready': True, 'warning': None}), \
             patch.object(server.subprocess, 'run', side_effect=AssertionError('No runtime installed')):
            state = server.status('ltx-video')
        self.assertTrue(state['installed'])
        self.assertFalse(state['available'])
        self.assertFalse(state['dependencies_ready'])
        self.assertTrue(state['blocked_reason'])
        self.assertNotIn('rerun its installer', state['blocked_reason'],
                         'A successful weights-only download must not cause an installer retry loop')


    def fake_api(self, revision='a' * 40):
        data = b'fixture model bytes'
        sibling = SimpleNamespace(rfilename='transformer/diffusion_pytorch_model.safetensors',
                                  size=len(data), lfs={'sha256': hashlib.sha256(data).hexdigest()})
        return Mock(model_info=Mock(return_value=SimpleNamespace(sha=revision, siblings=[sibling])))

    def test_plan_pins_revision_and_resume_does_not_requery_main(self):
        api = self.fake_api()
        with contextlib.redirect_stdout(io.StringIO()):
            plan = download_support.build_plan('ltx-video', {}, api=api)
            never_network = Mock(model_info=Mock(side_effect=AssertionError('Retry queried moving main')))
            resumed = download_support.build_plan('ltx-video', {}, api=never_network)
        self.assertEqual(plan, resumed)
        self.assertEqual(plan['models'][0]['revision'], 'a' * 40)
        api.model_info.assert_called_once()
        never_network.model_info.assert_not_called()
        self.assertTrue((self.root / 'ltx-video' / 'download-plan.json').is_file())
        self.assertFalse((self.root / 'ltx-video' / 'models').exists(), 'Metadata planning must not transfer weights')

    def test_explicit_revision_changes_plan_and_is_forwarded(self):
        download_support.build_plan('ltx-video', {}, api=self.fake_api())
        changed = self.fake_api('b' * 40)
        plan = download_support.build_plan('ltx-video', {'model': 'b' * 40}, api=changed)
        self.assertEqual(changed.model_info.call_args.kwargs['revision'], 'b' * 40)
        self.assertEqual(plan['models'][0]['revision'], 'b' * 40)

    def test_refresh_plan_explicitly_allows_new_main(self):
        download_support.build_plan('ltx-video', {}, api=self.fake_api())
        changed = self.fake_api('c' * 40)
        plan = download_support.build_plan('ltx-video', {}, refresh=True, api=changed)
        self.assertEqual(plan['models'][0]['revision'], 'c' * 40)
        changed.model_info.assert_called_once()

    def test_cached_plan_rejects_path_escape_without_network(self):
        plan = download_support.build_plan('ltx-video', {}, api=self.fake_api())
        plan['models'][0]['files'][0]['path'] = '../../../outside.bin'
        (self.root / 'ltx-video' / 'download-plan.json').write_text(json.dumps(plan))
        never_network = Mock(model_info=Mock(side_effect=AssertionError('Unexpected metadata request')))
        with self.assertRaises(ValueError):
            download_support.build_plan('ltx-video', {}, api=never_network)
        never_network.model_info.assert_not_called()

    def test_existing_symlink_cannot_redirect_model_outside_home(self):
        home = self.root / 'ltx-video'
        home.mkdir()
        outside = self.root / 'unrelated-directory'
        outside.mkdir()
        (home / 'models').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            download_support.safe_path(home, 'models/model/transformer/model.safetensors')

    def test_metadata_rejects_unpinned_revision_and_invalid_checksum(self):
        for revision, checksum in [('main', 'd' * 64), ('d' * 40, 'invalid-sha256')]:
            with self.subTest(revision=revision, checksum=checksum):
                api = self.fake_api(revision)
                api.model_info.return_value.siblings[0].lfs['sha256'] = checksum
                with self.assertRaises(ValueError):
                    download_support.build_plan('ltx-video', {}, refresh=True, api=api)
                self.assertFalse((self.root / 'ltx-video' / 'download-plan.json').exists())


    def prepared_download(self, expert='ltx-video'):
        data = b'fixture model bytes'
        api = self.fake_api()
        if expert == 'liveportrait':
            api.model_info.return_value.siblings[0].rfilename = 'liveportrait/base_models/appearance_feature_extractor.pth'
        download_support.build_plan(expert, {}, api=api)

        def transfer(**kwargs):
            self.assertEqual(kwargs['revision'], 'a' * 40)
            self.assertIs(kwargs['token'], False)
            for name in kwargs['allow_patterns']:
                target = Path(kwargs['local_dir']) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            return kwargs['local_dir']

        return Mock(side_effect=transfer)

    def test_plan_only_does_not_call_snapshot_or_write_receipt(self):
        self.prepared_download()
        snapshot = Mock(side_effect=AssertionError('Plan transferred weights'))
        with patch.dict(sys.modules, {'huggingface_hub': SimpleNamespace(snapshot_download=snapshot)}), \
             contextlib.redirect_stdout(io.StringIO()):
            install.download('ltx-video', {}, weights_only=True, plan_only=True)
        snapshot.assert_not_called()
        self.assertFalse((self.root / 'ltx-video' / 'models').exists())
        self.assertFalse((self.root / 'ltx-video' / 'weights-manifest.json').exists())

    def test_liveportrait_weights_only_requires_no_git_and_preserves_runtime_receipt(self):
        snapshot = self.prepared_download('liveportrait')
        home = self.root / 'liveportrait'
        previous = b'pre-existing runtime receipt must remain byte-identical'
        (home / 'install-manifest.json').write_bytes(previous)
        with patch.dict(sys.modules, {'huggingface_hub': SimpleNamespace(snapshot_download=snapshot)}), \
             patch.object(install.subprocess, 'run', side_effect=AssertionError('Unexpected subprocess')), \
             patch.object(install.subprocess, 'check_output', side_effect=AssertionError('Unexpected git call')), \
             patch.object(install.platform, 'platform', return_value='Linux test fixture'), \
             contextlib.redirect_stdout(io.StringIO()):
            install.download('liveportrait', {}, weights_only=True)
            install.verify('liveportrait')
        self.assertEqual((home / 'install-manifest.json').read_bytes(), previous)
        receipt = json.loads((home / 'weights-manifest.json').read_text())
        self.assertEqual(receipt['install_mode'], 'weights-only')
        self.assertIsNone(receipt['source'])
        self.assertFalse((home / 'source').exists())
        snapshot.assert_called_once()

    def test_upstream_checksum_failure_never_writes_success_receipt(self):
        snapshot = self.prepared_download()
        valid_transfer = snapshot.side_effect

        def corrupt(**kwargs):
            valid_transfer(**kwargs)
            for name in kwargs['allow_patterns']:
                path = Path(kwargs['local_dir']) / name
                path.write_bytes(b'X' * path.stat().st_size)

        snapshot.side_effect = corrupt
        with patch.dict(sys.modules, {'huggingface_hub': SimpleNamespace(snapshot_download=snapshot)}), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'SHA-256 mismatch'):
                install.download('ltx-video', {}, weights_only=True)
        self.assertFalse((self.root / 'ltx-video' / 'weights-manifest.json').exists())
        self.assertFalse((self.root / 'ltx-video' / 'install-manifest.json').exists())

    def test_stale_python_file_does_not_make_weights_only_available(self):
        snapshot = self.prepared_download()
        with patch.dict(sys.modules, {'huggingface_hub': SimpleNamespace(snapshot_download=snapshot)}), \
             contextlib.redirect_stdout(io.StringIO()):
            install.download('ltx-video', {}, weights_only=True)
        python = registry.python_path('ltx-video')
        python.parent.mkdir(parents=True)
        python.write_text('stale unverified environment')
        with patch.object(server, 'memory_check', return_value={'ready': True, 'warning': None}), \
             patch.object(server.subprocess, 'run', side_effect=AssertionError('Weights-only receipt is not a runtime')):
            state = server.status('ltx-video')
        self.assertTrue(state['weights_downloaded'])
        self.assertEqual(state['install_mode'], 'weights-only')
        self.assertFalse(state['available'])
        self.assertFalse(state['dependencies_ready'])


if __name__ == '__main__':
    unittest.main()
