# cosmo-dl

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Download cosmological simulation data with **resume**, **multi-threading**, **rate limiting**, **rich progress bars**, and **recursive crawling**.

## Supported Simulations

| Source | Simulations | Auth |
|--------|-------------|------|
| **IllustrisTNG** | TNG50, TNG100, TNG300, TNG-Cluster, Illustris (66 sims) | API key |
| **EAGLE** | Fiducial_models, Physics_vars, DMONLY (26 sims) | Basic Auth |
| **FIRE2** | Core, Massive Halo, High Redshift, Boxes — auto-discovered | None |
| **Auriga** | ICs, level3, level4 (external Globus link) | None |

## Quick Start

```bash
git clone https://github.com/yxi/cosmo-dl.git
cd cosmo-dl
pip install -e .  # or `uv sync --no-dev` if using uv
```

## CLI Usage

### Download

```bash
# Single file with SHA256 verification (8 threads)
cosmo-dl download https://example.com/snapshot_127.0.hdf5 -o ./data/ -w 8 --hash sha256

# Recursively download all HDF5 files from a directory listing
cosmo-dl download https://example.com/data/ --recursive --include "*.hdf5" -w 8

# Download from a built-in source
cosmo-dl download FIRE2/m11i_res7100 -o ./fire-data/ -w 8 --limit 2MB/s

# EAGLE with Basic Auth
cosmo-dl download EAGLE/Physics_vars/FBconstL0050N0752/snapshots/sn-28 -o ./eagle/
```

### Browse sources

```bash
cosmo-dl source              # table of all sources
cosmo-dl source TNG          # drill into a source
cosmo-dl source TNG/TNG50    # drill deeper
cosmo-dl source TNG/TNG50/TNG50-1  # show file categories
```

### Explore URLs

```bash
cosmo-dl explore https://example.com/sims/ --include "*.hdf5" --depth 2
```

### Configuration

```bash
cosmo-dl config set tng_api_key "your-key"    # store a token
cosmo-dl config get tng_api_key               # read a value (shows source)
cosmo-dl config show                          # all settings
cosmo-dl config show --auth                   # authentication status
cosmo-dl config unset tng_api_key             # remove a token
```

Or use environment variables / `.env`:

| Variable | For |
|----------|-----|
| `TNG_API_KEY` | IllustrisTNG API |
| `EAGLE_USERNAME` | EAGLE basic auth |
| `EAGLE_PASSWORD` | EAGLE basic auth |

## Python API

```python
import cosmo_dl

# List sources
print(cosmo_dl.list_sources())  # ["Auriga", "EAGLE", "FIRE2", "TNG"]

# Download a single file with rich progress bar
result = cosmo_dl.download(
    "FIRE2/m11i_res7100",
    workers=8,
    output_dir="./data/",
    expected_hash="sha256",
)
print(result.success, result.speed, result.checksum)

# Explore a directory listing
files = cosmo_dl.explore("https://example.com/sims/", recursive=True)
for f in files:
    print(f.name, f.size)

# Low-level engine (full control)
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

Then: `cosmo-dl download my-sim/snap-100 -w 8`

## Development

```bash
git clone https://github.com/yxi/cosmo-dl.git
cd cosmo-dl

uv sync                    # install deps + dev tools
uv run pre-commit install  # enable ruff + mypy hooks
uv run pytest -v           # run tests
```

Dependencies: `requests`, `rich`, `rich-click`, `pyyaml`. Dev: `ruff`, `mypy`, `pytest`.

## License

MIT — see [LICENSE](LICENSE).
