"""YAML source loader with env-var substitution."""
import os
import re
import yaml

from cosmo_dl.engine.types import AuthConfig
from cosmo_dl.registry.source import DatasetInfo, SimulationSource


def load_sources_from_yaml(path: str) -> list[SimulationSource]:
    """Load simulation sources from a YAML configuration file.

    Each top-level key under ``sources`` names a source.  The YAML text is
    preprocessed to substitute ``${VAR}`` placeholders with environment
    variables before parsing.

    Returns an empty list when *path* does not exist.
    """
    if not os.path.isfile(path):
        return []

    with open(path, "r") as fh:
        raw_text = fh.read()

    # Substitute ${VAR} with environment variable values.
    substituted = _substitute_env(raw_text)

    data = yaml.safe_load(substituted) or {}
    sources_dict = data.get("sources", {}) or {}

    result: list[SimulationSource] = []
    for name, cfg in sources_dict.items():
        cfg = cfg or {}

        # -- auth --
        auth = None
        auth_cfg = cfg.get("auth")
        if auth_cfg:
            auth = AuthConfig(
                type=auth_cfg.get("type", "none"),
                username=auth_cfg.get("username"),
                password=auth_cfg.get("password"),
                token=auth_cfg.get("token"),
                cookie_file=auth_cfg.get("cookie_file"),
                custom_headers=auth_cfg.get("custom_headers", {}),
            )

        # -- datasets --
        datasets: dict[str, DatasetInfo] = {}
        for ds_name, ds_cfg in (cfg.get("datasets") or {}).items():
            ds_cfg = ds_cfg or {}
            datasets[ds_name] = DatasetInfo(
                path=ds_cfg["path"],
                description=ds_cfg.get("description", ""),
                pattern=ds_cfg.get("pattern"),
                chunks=ds_cfg.get("chunks"),
            )

        source = SimulationSource(
            name=name,
            description=cfg.get("description", ""),
            base_url=cfg["base_url"],
            auth=auth,
            structure=cfg.get("structure", "mirror"),
            datasets=datasets,
        )
        result.append(source)

    return result


def _substitute_env(text: str) -> str:
    """Replace ``${VAR}`` placeholders with environment variable values."""
    return re.sub(
        r"\$\{(\w+)\}",
        lambda m: os.environ.get(m.group(1), m.group(0)),
        text,
    )
