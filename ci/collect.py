"""Collect validated package, logs, and corresponding source for CI artifacts."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

root = Path.cwd()
summary = json.loads((root / 'state/last-success.json').read_text())
package = root / summary['package']
with package.open('rb') as stream:
    package_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
if package_sha != summary['package_sha256']:
    raise RuntimeError('Package hash mismatch')
run = package.parent.parent
dest = root / 'ci-artifacts'
dest.mkdir()
shutil.copy2(package, dest / package.name)
shutil.copy2(package.parent / 'PKGBUILD', dest / 'PKGBUILD')
shutil.copy2(run / 'summary.json', dest / 'summary.json')
shutil.copy2(run / 'artifact-manifest.json', dest / 'artifact-manifest.json')
logs = dest / 'logs'
logs.mkdir()
for log in run.glob('*.log'):
    shutil.copy2(log, logs / log.name)
# Includes initialized third-party source and build instructions, omits build products.
source = dest / ('anyps5-source-' + summary['commit'] + '.tar.gz')
with source.open('wb') as stream:
    subprocess.run(['docker', 'run', '--rm', '--entrypoint', 'tar',
                    summary['tags']['builder'], '-C', '/home/builder',
                    '--exclude=.git', '--exclude=source/build-full',
                    '--exclude=source/build-relinker', '-czf', '-', 'source'],
                   stdout=stream, check=True)
with (dest / 'SHA256SUMS').open('w') as output:
    for path in sorted(dest.iterdir()):
        if path.is_file() and path.name != 'SHA256SUMS':
            with path.open('rb') as stream:
                sha = hashlib.file_digest(stream, 'sha256').hexdigest()
            output.write(f'{sha}  {path.name}\n')
print('Collected validated artifacts at', dest)
