#!/usr/bin/env python3
"""Local AnyPS5 build, minification, packaging, and validation. Linux only."""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import uuid

ROOT = Path(__file__).resolve().parent
UPSTREAM = 'https://github.com/boykopovar/AnyPS5.git'
ARCH = 'archlinux@sha256:4e77cf2ea5f410e6f8be5abf93ccf17ce2436e87a138c167208356711a405dbd'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def manifest(path):
    result = {}
    for item in sorted(Path(path).rglob('*')):
        key = str(item.relative_to(path))
        if item.is_symlink():
            result[key] = ['link', os.readlink(item)]
        elif item.is_file():
            result[key] = ['file', digest(item), item.stat().st_mode & 0o777]
    return result


def execute(argv, *, cwd=ROOT, log=None, capture=False):
    print('+', shlex.join(map(str, argv)), flush=True)
    if capture:
        return subprocess.check_output(argv, cwd=cwd, text=True).strip()
    if log is None:
        subprocess.run(argv, cwd=cwd, check=True)
        return
    with Path(log).open('w') as stream:
        process = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        try:
            for line in process.stdout:
                print(line, end='', flush=True)
                stream.write(line)
            status = process.wait()
        except BaseException:
            process.terminate()
            process.wait()
            raise
    if status:
        raise subprocess.CalledProcessError(status, argv)


def build(args):
    if os.geteuid() == 0:
        raise RuntimeError('Run as your normal user; makepkg must not run as root.')
    for binary in ['docker', 'mint', 'git', 'makepkg', 'namcap', 'tar', 'bash']:
        if not shutil.which(binary):
            raise RuntimeError(f'Missing command: {binary}')
    prefix = [] if args.no_sudo else ['sudo']
    docker = prefix + ['docker']
    execute(docker + ['info'], log=ROOT / 'state/docker-info.log')
    if args.commit:
        commit = args.commit
    else:
        head = execute(['git', 'ls-remote', UPSTREAM, 'HEAD'], capture=True)
        commit = head.split()[0]
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise RuntimeError('Commit must be a full 40-character lowercase Git SHA.')
    version_text = execute(['mint', '--version'], capture=True)
    inputs = {'commit': commit, 'arch_image': ARCH, 'mint': version_text,
              'docker_api': args.docker_api, 'jobs': args.jobs}
    for name in ['Dockerfile', 'PKGBUILD.template', 'pipeline.py']:
        inputs[name] = digest(ROOT / name)
    fingerprint = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    success_file = ROOT / 'state/last-success.json'
    if success_file.exists() and not args.force:
        last = json.loads(success_file.read_text())
        package = ROOT / last['package']
        if (last['fingerprint'] == fingerprint and package.is_file()
                and digest(package) == last['package_sha256']):
            print(f'Unchanged: validated package already exists at {package}')
            return

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')
    run_id = stamp + '-' + uuid.uuid4().hex[:6]
    out = ROOT / 'output' / run_id
    out.mkdir(parents=True)
    (out / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
    tags = {k: f'anyps5-pipeline:{k}-{run_id}' for k in ['builder', 'artifacts', 'minimal']}
    build_options = ['--build-arg', f'UPSTREAM_COMMIT={commit}',
                     '--build-arg', f'ARCH_IMAGE={ARCH}', '--build-arg', f'JOBS={args.jobs}']
    for target in ['builder', 'artifacts']:
        execute(docker + ['build', '--progress=plain', '--target', target,
                         '-t', tags[target]] + build_options + ['.'],
                log=out / f'build-{target}.log')

    def extract(image, destination):
        destination.mkdir()
        container = execute(docker + ['create', image], capture=True)
        try:
            execute(docker + ['cp', f'{container}:/opt/anyps5/.', str(destination)])
        finally:
            execute(docker + ['rm', container])
        if prefix:
            execute(['sudo', 'chown', '-R', f'{os.getuid()}:{os.getgid()}', str(destination)])

    extract(tags['artifacts'], out / 'original')
    execute(prefix + ['mint', '--crt-api-version', args.docker_api, 'slim',
                     '--target', tags['artifacts'], '--tag', tags['minimal'],
                     '--http-probe=false', '--continue-after=10',
                     '--include-path=/opt/anyps5', '--include-exe=sleep',
                     '--include-shell', '--exec', '/opt/anyps5/relinker --help'],
            cwd=out, log=out / 'mint.log')
    extract(tags['minimal'], out / 'minimal')
    original = manifest(out / 'original')
    if original != manifest(out / 'minimal'):
        raise RuntimeError('Minification changed artifact contents or permissions.')
    if (out / 'minimal/upstream-commit.txt').read_text().strip() != commit:
        raise RuntimeError('Extracted commit does not match the requested commit.')
    if not (out / 'minimal/LICENSE').stat().st_size:
        raise RuntimeError('Missing license.')
    (out / 'artifact-manifest.json').write_text(json.dumps(original, indent=2) + '\n')
    execute(docker + ['run', '--rm', '--entrypoint', '/opt/anyps5/relinker',
                     tags['minimal'], '--help'], log=out / 'minimal-startup.log')

    packdir = out / 'packaging'
    packdir.mkdir()
    archive = packdir / 'anyps5-local.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for name in ['relinker', 'libs', 'LICENSE', 'upstream-commit.txt']:
            tar.add(out / 'minimal' / name, arcname=name)
    pkgver = f'0.{stamp}.g{commit[:12]}'
    recipe = (ROOT / 'PKGBUILD.template').read_text()
    recipe = recipe.replace('@VERSION@', pkgver).replace('@CHECKSUM@', digest(archive))
    (packdir / 'PKGBUILD').write_text(recipe)
    execute(['bash', '-n', str(packdir / 'PKGBUILD')])
    execute(['makepkg', '--cleanbuild', '--noconfirm'], cwd=packdir, log=out / 'makepkg.log')
    package = packdir / f'anyps5-local-bin-{pkgver}-1-x86_64.pkg.tar.zst'
    if not package.is_file():
        raise RuntimeError('Expected package not found; check makepkg output settings.')
    execute(['namcap', 'PKGBUILD'], cwd=packdir, log=out / 'namcap-recipe.log')
    execute(['namcap', str(package)], cwd=packdir, log=out / 'namcap-package.log')
    for log in ['namcap-recipe.log', 'namcap-package.log']:
        if re.search(r'^.*\sE:\s', (out / log).read_text(), re.MULTILINE):
            raise RuntimeError(f'Namcap errors in {log}')

    # Extract our own locally generated package and compare installed payload bytes.
    payload = out / 'package-payload'
    payload.mkdir()
    execute(['tar', '-xf', str(package), '-C', str(payload)])
    if digest(payload / 'usr/bin/anyps5-relinker') != digest(out / 'minimal/relinker'):
        raise RuntimeError('Packaged relinker differs from validated executable.')
    if manifest(payload / 'usr/lib/anyps5') != manifest(out / 'minimal/libs'):
        raise RuntimeError('Packaged libraries differ from validated artifacts.')
    for name, dest in [('LICENSE', 'usr/share/licenses/anyps5-local-bin/LICENSE'),
                       ('upstream-commit.txt', 'usr/share/doc/anyps5-local-bin/upstream-commit.txt')]:
        if digest(payload / dest) != digest(out / 'minimal' / name):
            raise RuntimeError(f'Packaged {name} differs.')

    # The regression environment retains the builder runtime libraries.
    mount = f'type=bind,src={payload / "usr/bin/anyps5-relinker"},dst=/home/builder/source/build-full/core/relinker/relinker,readonly'
    execute(docker + ['run', '--rm', '--mount', mount, '--entrypoint', 'bash', tags['builder'],
                     '-lc', 'ctest --test-dir /home/builder/source/build-full --output-on-failure --no-tests=error'],
            log=out / 'packaged-relinker-tests.log')
    clean_script = '''set -e
pacman -Syu --noconfirm
printf '\\nNoExtract = !usr/share/doc !usr/share/doc/*\\n' >> /etc/pacman.conf
pacman -U --noconfirm /packages/*.pkg.tar.zst
anyps5-relinker --help
pacman -Qkk anyps5-local-bin
test -s /usr/share/doc/anyps5-local-bin/upstream-commit.txt
test -s /usr/share/licenses/anyps5-local-bin/LICENSE
test -s /usr/lib/anyps5/libkernel.prx
test -s /usr/lib/anyps5/libSceAgcDriver.prx
echo 'PASS: clean installation, integrity, and startup.'
'''
    execute(docker + ['run', '--rm', '--mount', f'type=bind,src={packdir},dst=/packages,readonly',
                     ARCH, 'bash', '-lc', clean_script], log=out / 'clean-install.log')
    sizes = {}
    for name, tag in tags.items():
        sizes[name] = int(execute(docker + ['image', 'inspect', tag, '--format', '{{.Size}}'], capture=True))
    summary = {'commit': commit, 'tags': tags, 'image_bytes': sizes,
               'package': str(package.relative_to(ROOT)), 'package_sha256': digest(package),
               'fingerprint': fingerprint,
               'limits': 'Skipped tests remain unvalidated. No game execution test. Regression environment uses builder runtime libraries.'}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    temp = success_file.with_suffix('.tmp')
    temp.write_text(json.dumps(summary, indent=2) + '\n')
    temp.replace(success_file)
    print('\nPASS: validated local package:', package)
    print('Summary and logs:', out)
    print('No package was installed or published by this pipeline.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', help='Build this full commit instead of upstream HEAD')
    parser.add_argument('--force', action='store_true', help='Rebuild even if inputs are unchanged')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--docker-api', default='1.40')
    parser.add_argument('--no-sudo', action='store_true', help='Docker/Mint already accessible without sudo')
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    (ROOT / 'state').mkdir(exist_ok=True)
    with (ROOT / 'state/pipeline.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, 'Another pipeline run is active.\n')
        try:
            build(args)
        except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
            parser.exit(1, f'FAILED: {exc}\nSuccess state was not updated; inspect the latest output directory.\n')


if __name__ == '__main__':
    main()
