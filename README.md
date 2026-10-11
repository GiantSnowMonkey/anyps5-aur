# AnyPS5 Arch builder — local pipeline

Docker builds and tests AnyPS5 at an exact upstream commit, Mint minimizes an
artifact image, and makepkg produces a local Arch package. Nothing is installed
on the host or published automatically.

## Run from Fish

Prerequisites: Docker running, Python 3.11+, Git, base-devel, namcap, tar, and
the working Mint + mint-sensor installation from this session.

```fish
paru -S --needed python git base-devel namcap tar
python pipeline.py --commit a18aaeaa396dc2cf6034a92422239714b956c85c
```

First validate the same commit we have already tested. This consolidated
Dockerfile changes the build layout and will do a new initial build.

After success, check and build current upstream HEAD:

```fish
python pipeline.py
```

An unchanged commit and configuration skips work only when the previously
validated package still exists and its SHA-256 matches. Configuration includes
the Dockerfile, recipe, pipeline code, Mint version, build jobs and API setting.
The most recent successful run is recorded in `state/last-success.json`.
Failures leave that record unchanged. A lock prevents concurrent runs.

```fish
python pipeline.py --force
python pipeline.py --jobs 2
python pipeline.py --help
```

Do not run the script with sudo. It uses sudo only for Docker/Mint and ownership
of extracted files; makepkg runs as your user. `--no-sudo` is available if Docker
and Mint are already accessible without sudo. Run `sudo -v` before a long build;
sudo may ask again if the cached authorization expires.

## Outputs and checks

Each run has its own directory under `output/`, including logs, original and
minimized files, package extraction, PKGBUILD, package, and summary JSON.
Unique Docker tags avoid confusing a failed run with an old successful image.
No images or build cache are automatically deleted.

Checks:

1. Relinker-only and full upstream builds and CTest runs.
2. Mint completion and exact artifact contents/permissions comparison.
3. Minimized relinker startup.
4. Package SHA-256, Namcap errors, and package payload byte comparison.
5. CTest with the packaged relinker mounted into the builder test environment.
6. Fresh Arch container installation, relinker startup, and pacman integrity.

Namcap warnings remain in logs; any `E:` finding fails the pipeline. Some
upstream tests skip without a GPU/display. Read the CTest logs; zero failures
does not mean those skipped cases passed. The packaged relinker regression run
uses builder runtime libraries. No actual game execution has been validated.

The minimized image is an artifact carrier, not a complete game runtime. All
files under `libs/`, including `unpatched/`, are deliberately retained until
their runtime and development roles are checked. The image is smaller, but
this is not a claim of the smallest possible image.

The base image digest is pinned to the image already tested in this session.
Arch repository packages still roll; pinned source and base do not make this
a bit-for-bit reproducible build. `--force` reruns validation but Docker may
reuse dependency layers. Update the base digest or Dockerfile dependency layer
when refreshing the toolchain is intended. Skipping upstream changes also
does not track dependency security updates.

The local version uses the UTC build timestamp and commit. Release automation
will need an upstream version policy. Existing makepkg settings such as
`PKGDEST` can redirect output; the script fails if the package is not in its
expected run directory. Use default output settings for this first run.

The archive and recipe are for local validation. AUR publication requires
publicly accessible sources; distributing GPL binaries also requires making
the corresponding source available under the license terms. No AUR/GitHub
publishing, secrets, background scheduler, or automatic host installation is
included in this version.

## Script checks

```fish
python -m unittest -v test_pipeline.py
```

The supplied pipeline has been syntax-checked and its skip/integrity logic
tested. Its consolidated Docker workflow still needs its first run on your
machine.
