# Install details and offline recipe

The short install steps are in [README.md](README.md). This page has the disk sizes, the extras detail and the offline recipe for a CGC workspace that cannot reach GitHub or PyPI.

Labels: VERIFIED means run and seen to work on macOS arm64 on 2026-11-16 (commit `baddbea`). NOT VERIFIED means not run as written. Nothing has been run on Linux or in CGC yet.

## Extras and errors

* Without `[yaml]`, a YAML config stops with `config error: YAML configs require PyYAML: pip install 'synthpediatric[yaml]'`.
* Without `[validate]`, `validate` stops with `The discriminator AUC needs scikit-learn`.
* On Python 3.14, `[validate]` cannot be installed (scikit-learn 1.5.2 has no 3.14 wheel). Core plus `[yaml]` installs fine.
* Disk: about 200 MB for the core install, about 305 MB with `[yaml,validate]`.

## Offline install (wheelhouse)

Build a wheelhouse on a machine with internet access, upload it to CGC, and install with no network:

```bash
# on a connected machine, in a Python 3.12 venv with pip:
git clone https://github.com/cloudr-solutions/synthpediatric.git
pip wheel --no-deps ./synthpediatric -w wheelhouse                     # VERIFIED (96 KB wheel)
pip download "synthpediatric[yaml,validate]" --find-links wheelhouse \
  --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux_2_28_x86_64 \
  --only-binary=:all: --python-version 3.12 --implementation cp -d wheelhouse   # VERIFIED (download only)

# in CGC, after uploading wheelhouse/:
pip install --no-index --find-links wheelhouse "synthpediatric[yaml,validate]"   # NOT VERIFIED on Linux
```

To build a specific version, run `git checkout jamboree-2026-11-16` (or a commit sha) inside the clone before `pip wheel`. NOT VERIFIED with a tag; the same step with a commit sha is the form that was tested.

Set `--python-version` to the CGC Python (`python3 --version`). The wheels must match the CGC Python version and Linux; Mac wheels do not work there. The offline install step was VERIFIED on the Mac with Mac wheels (`uv pip install --offline --no-index --find-links`, Python 3.12), and `measure` then passed its audit.

## Bundle sizes

Measured for Linux x86_64 wheels (download only):

| Python | Core only (JSON configs) | `[yaml]` | `[yaml,validate]` |
|---|---|---|---|
| 3.10 | 77 MB, 8 files | 78 MB | 127 MB, 14 files |
| 3.12 | 80 MB, 7 files | 81 MB | 127 MB, 13 files |
| 3.13 | | | 127 MB |
| 3.14 | | 81 MB | not possible (no scikit-learn 1.5.2) |

## glibc

pyarrow is the largest file (48 to 53 MB). The newest pyarrow, pandas and numpy wheels need glibc 2.28. If the CGC image has an older glibc (check with `ldd --version`), download with only `--platform manylinux2014_x86_64`. Pip then picks older wheels (pyarrow 20.0.0) and the `[yaml,validate]` bundle is 116 to 119 MB. Every dependency has a Linux wheel either way.

To bring the examples too, upload the cloned folder (1.2 MB).
