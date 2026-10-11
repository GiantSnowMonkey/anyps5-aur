import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import pipeline


class PipelineTests(unittest.TestCase):
    def test_manifest_detects_changed_bytes_and_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / 'relinker'
            file.write_bytes(b'original')
            before = pipeline.manifest(root)
            file.write_bytes(b'changed')
            self.assertNotEqual(before, pipeline.manifest(root))
            file.write_bytes(b'original')
            file.chmod(0o755)
            self.assertNotEqual(before, pipeline.manifest(root))

    def test_skip_requires_valid_package_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'state').mkdir()
            for name in ['Dockerfile', 'PKGBUILD.template', 'pipeline.py']:
                (root / name).write_text(name)
            package = root / 'package.pkg.tar.zst'
            package.write_bytes(b'package')
            commit = 'a' * 40
            args = argparse.Namespace(commit=commit, force=False, no_sudo=True,
                                      docker_api='1.40', jobs=4)
            inputs = dict(commit=commit, arch_image=pipeline.ARCH, mint='mint-test',
                          docker_api='1.40', jobs=4)
            for name in ['Dockerfile', 'PKGBUILD.template', 'pipeline.py']:
                inputs[name] = pipeline.digest(root / name)
            fingerprint = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
            state = dict(fingerprint=fingerprint, package=package.name,
                         package_sha256=pipeline.digest(package))
            state_path = root / 'state/last-success.json'
            state_path.write_text(json.dumps(state))
            def fake_execute(argv, **kwargs):
                if argv == ['mint', '--version']:
                    return 'mint-test'
                if 'build' in argv:
                    raise subprocess.CalledProcessError(1, argv)
            with patch.object(pipeline, 'ROOT', root), patch.object(pipeline.os, 'geteuid', return_value=1000), patch.object(pipeline.shutil, 'which', return_value='/tool'), patch.object(pipeline, 'execute', side_effect=fake_execute) as calls:
                pipeline.build(args)
                self.assertFalse(any('build' in c.args[0] for c in calls.call_args_list))
                package.write_bytes(b'corrupt')
                before = state_path.read_bytes()
                with self.assertRaises(subprocess.CalledProcessError):
                    pipeline.build(args)
                self.assertEqual(before, state_path.read_bytes())


if __name__ == '__main__':
    unittest.main()
