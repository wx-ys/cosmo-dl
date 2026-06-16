# cosmo-dl

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Download cosmological simulation data with **resume**, **multi-thread**, **rate limiting**, **progress bars**, and **recursive directory crawling** — from the command line or as a Python library.

## Features

- **Resumable downloads** — HTTP Range requests, `.part` files, pick up where you left off
- **Multi-threaded** — split large files into chunks and download in parallel
- **Rate limiting** — token bucket algorithm, e.g. `--limit 10M`
- **Progress bars** — `tqdm` integration, per-file and overall progress
- **Recursive crawling** — parse Apache/Nginx/Globus HTML directory listings, discover all files
- **File integrity** — verify with MD5, SHA256, or file size checks
- **Mirror URL structure** — preserves remote directory hierarchy on disk
- **Pre-configured sources** — FIRE, Auriga built in; add your own via YAML
- **CLI + Python API** — use as a command-line tool or import in scripts

## Quick Start

### Installation

```bash
pip install cosmo-dl
```

Or from source:

```bash
git clone https://github.com/yxi/cosmo-dl.git
cd cosmo-dl
uv sync
```

### CLI Usage

```bash
# Download a single file
cosmo-dl download https://example.com/data/snapshot_127.0.hdf5 -o ./data/

# Recursively download all HDF5 files under a URL
cosmo-dl download https://example.com/data/ --recursive --include "*.hdf5" -w 8

# Use a pre-configured simulation source
cosmo-dl download FIRE/m11i_res7100 --workers 8 --limit 20M -o ./fire-data/

# Explore what's available at a URL
cosmo-dl explore https://example.com/sims/ --recursive --include "*.hdf5"

# List known simulation sources
cosmo-dl source list

# Show source details
cosmo-dl source info FIRE
```

### Python API

```python
import cosmo_dl

# High-level: one-liner download
result = cosmo_dl.download("FIRE/m11i_res7100", workers=8, output_dir="./data/")
print(result.success, result.speed)

# Explore a URL
files = cosmo_dl.explore("https://example.com/sims/", recursive=True)
for f in files:
    print(f.name, f.size)

# List known simulation sources
print(cosmo_dl.list_sources())  # ["Auriga", "FIRE", ...]

# Low-level: full control over engine components
from cosmo_dl.engine import Downloader, Session, RateLimiter

session = Session(auth=("bearer", "your-token"), retry=5)
limiter = RateLimiter("10M")
dl = Downloader(session=session, rate_limiter=limiter)

result = dl.download(
    "https://example.com/snap.hdf5",
    "./local.hdf5",
    workers=8,
    expected_hash="sha256:abc123...",
)
```

## Built-in Simulation Sources

| Source | Description | Auth |
|--------|-------------|------|
| **FIRE** | FIRE-2 public release (Flatiron Institute) — M11i, M12i | None |
| **Auriga** | Auriga simulation, halos 1–30, level 4 | None |
| **IllustrisTNG** | TNG50-1, TNG100-1, TNG300-1 — group catalogs & snapshots | API key |

Set the TNG API key via environment variable:

```bash
export TNG_API_KEY="your-api-key-here"
cosmo-dl explore TNG50-1/groupcat-99
cosmo-dl download TNG50-1/groupcat-99 -w 8 -o ./tng-data/
```

## Custom Sources (YAML)

Add your own simulation sources via `~/.config/cosmo-dl/sources.yaml`:

```yaml
sources:
  my-sim:
    description: My custom simulation
    base_url: https://myserver.edu/data/
    auth:
      type: basic
      username: ${MY_USER}      # env var substitution
      password: ${MY_PASS}
    datasets:
      snap-100:
        path: snapdir_100/
        pattern: "snapshot_100.{chunk}.hdf5"
        chunks: 8
        description: Snapshot 100
```

Then use it like any built-in source:

```bash
cosmo-dl download my-sim/snap-100 -w 8
```

## Architecture

```
┌─────────────────────────────────┐
│  CLI + Python API               │  cosmo-dl download|explore|source
├─────────────────────────────────┤
│  Registry                       │  SimulationSource, YAML configs
├─────────────────────────────────┤
│  Engine                         │  Downloader, Explorer, FileManager,
│                                  │  Session, RateLimiter
└─────────────────────────────────┘
```

Each layer depends only on the layer below. The Engine layer has zero astronomy-specific code — it can be reused independently for any file downloading task.

## Requirements

- Python ≥ 3.10
- `httpx` — HTTP client
- `tqdm` — progress bars
- `click` — CLI framework
- `pyyaml` — YAML config parsing
- `tomli` — TOML config parsing (stdlib `tomllib` on 3.11+)

## Development

```bash
git clone https://github.com/yxi/cosmo-dl.git
cd cosmo-dl
uv sync                    # install all dependencies
uv run pytest -v           # run 101 tests
```

## License

MIT
