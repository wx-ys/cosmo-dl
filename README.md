# cosmo-dl

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Download cosmological simulation data with **resume**, **multi-thread**, **rate limiting**, **rich progress bars**, and **recursive directory crawling**.

## Features

- **Resumable downloads** — chunk-level resume via `.part.meta` sidecar; interrupted downloads pick up where they left off
- **Multi-threaded** — splits large files into ~200 MiB chunks, downloads in parallel via HTTP Range requests
- **Rate limiting** — token bucket algorithm, e.g. `--limit 2MB/s`
- **Rich progress bars** — animated spinner, coloured bar, transfer speed, and ETA (powered by `rich`)
- **File integrity** — verify with MD5 or SHA256 (`--hash md5` / `--hash sha256`)
- **Recursive crawling** — parses Apache/Nginx directory listings to discover all files under a URL
- **Mirrors remote structure** — preserves the remote directory hierarchy on disk
- **Pre-configured sources** — EAGLE, FIRE, Auriga, IllustrisTNG; add your own via YAML
- **CLI + Python API** — use as a command-line tool or import in scripts

## Quick Start

```bash
pip install cosmo-dl
```

Or from source:

```bash
git clone https://github.com/yxi/cosmo-dl.git
cd cosmo-dl
uv sync
```

## CLI Usage

### Download

```bash
# Single file, 8 threads, verify with SHA256
cosmo-dl download https://example.com/snapshot_127.0.hdf5 -o ./data/ -w 8 --hash sha256

# Recursively crawl and download all HDF5 files
cosmo-dl download https://example.com/data/ --recursive --include "*.hdf5" -w 8

# Download from a built-in source
cosmo-dl download FIRE/m11i_res7100 -o ./fire-data/ -w 8 --limit 2MB/s

# EAGLE (Basic Auth — set env vars first)
cosmo-dl download EAGLE/Physics_vars/FBconstL0050N0752/snapshots/sn-28 -o ./eagle/
```

### Browse sources

```bash
cosmo-dl source list              # root-level table
cosmo-dl source list EAGLE        # drill into a source
cosmo-dl source info FIRE         # show metadata
cosmo-dl source discover TNG      # force lazy-load children
```

### Explore a URL

```bash
cosmo-dl explore https://example.com/sims/ --include "*.hdf5" --depth 2
```

### Authentication

```bash
cosmo-dl auth status                         # show all keys
cosmo-dl auth set tng_api_key "your-key"     # store a token
cosmo-dl auth unset tng_api_key              # remove a token
```

### Configuration

```bash
cosmo-dl config show               # all settings
cosmo-dl config set eagle_username "user"
cosmo-dl config get tng_api_key
```

**Environment variables** (or `.env` file):

| Variable | Config key |
|----------|-----------|
| `TNG_API_KEY` | `tng_api_key` |
| `EAGLE_USERNAME` | `eagle_username` |
| `EAGLE_PASSWORD` | `eagle_password` |

## Python API

```python
import cosmo_dl

# List sources
print(cosmo_dl.list_sources())  # ["Auriga", "EAGLE", "FIRE", ...]

# Download — one call
result = cosmo_dl.download(
    "FIRE/m11i_res7100", workers=8, output_dir="./data/",
    expected_hash="sha256",
)
print(result.success, result.speed, result.checksum)

# Explore
files = cosmo_dl.explore("https://example.com/sims/", recursive=True)
for f in files:
    print(f.name, f.size)
```

### Low-level engine

```python
from cosmo_dl.engine import Downloader, Session, RateLimiter

session = Session(auth=("bearer", "your-token"))
limiter = RateLimiter("10M")
dl = Downloader(session=session, rate_limiter=limiter)

result = dl.download(
    "https://example.com/snap.hdf5",
    "./local.hdf5",
    workers=8,
    expected_hash="sha256:abc123...",
)
```

## Built-in Sources

| Source | Description | Auth |
|--------|-------------|------|
| **EAGLE** | RefL0100N1504, FBconstL0050N0752 | Basic Auth |
| **FIRE** | FIRE-2 public release (Flatiron Institute) — M11i, M12i | None |
| **Auriga** | Auriga simulation, halos 1–30, level 4 | None |
| **IllustrisTNG** | TNG50-1, TNG100-1, TNG300-1 | API key |

## Custom Sources (YAML)

Add your own via `~/.config/cosmo-dl/sources.yaml`:

```yaml
sources:
  my-sim:
    description: My custom simulation
    base_url: https://myserver.edu/data/
    auth:
      type: basic
      username: ${MY_USER}
      password: ${MY_PASS}
    datasets:
      snap-100:
        path: snapdir_100/
        pattern: "snapshot_100.{chunk}.hdf5"
        chunks: 8
```

Then:

```bash
cosmo-dl download my-sim/snap-100 -w 8
```

## Architecture

```
┌────────────────────────────────────┐
│  CLI (rich-click)                  │  download | explore | source | auth | config
├────────────────────────────────────┤
│  Registry                          │  SourceNode tree + YAML configs
├────────────────────────────────────┤
│  Engine                            │  Downloader, Explorer, FileManager,
│                                    │  Session, RateLimiter
└────────────────────────────────────┘
```

The Engine layer contains zero astronomy-specific code — it works for any file downloading task.

## Development

```bash
git clone https://github.com/yxi/cosmo-dl.git
cd cosmo-dl

uv sync                    # install deps + dev tools
uv run pre-commit install  # enable ruff + mypy hooks
uv run pytest -v           # 172 tests
```

Dependencies: `requests`, `tqdm`, `click` / `rich-click`, `rich`, `pyyaml`, `tomli` (Python < 3.11).

Dev: `ruff` (linter + formatter), `mypy` (type checker), `pytest`.

## License

MIT
