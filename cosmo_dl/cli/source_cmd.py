"""CLI command: source — browse the simulation source tree."""
from __future__ import annotations

import click
from cosmo_dl.registry.registry import Registry


@click.group("source")
def source_cmd() -> None:
    """Browse simulation data sources (like a directory tree)."""
    pass


@source_cmd.command("list")
@click.argument("path", required=False, default="")
def source_list(path: str) -> None:
    """List contents of a source tree node.

    \b
    Examples:
      cosmo-dl source list               # show all root groups
      cosmo-dl source list TNG           # show TNG sub-groups
      cosmo-dl source list TNG/TNG50     # show TNG50 simulations
      cosmo-dl source list TNG/TNG50/TNG50-1  # show file categories
      cosmo-dl source list TNG/TNG50/TNG50-1/groupcat  # show indices
    """
    reg = Registry()

    if not path:
        # Show root level
        roots = reg.roots
        for name in sorted(roots.keys()):
            root = roots[name]
            loaded = root.is_loaded()
            count = root.child_count
            count_str = f"({count})" if count > 0 else ""
            loaded_str = "" if loaded else " [lazy]"
            click.echo(f"  {name}/{count_str:<6s}  {root.description}{loaded_str}")
        click.echo(f"\n  {len(roots)} source(s). Use 'source list <name>' to explore.")
        return

    node = reg.get_node(path)
    if node is None:
        click.echo(f"Path not found: {path!r}")
        raise SystemExit(1)

    # Show node info
    type_label = {
        "group": "[group]", "category": "[category]",
        "dataset": "[dataset]", "simulation": "[simulation]",
    }
    label = type_label.get(node.node_type, "")
    click.echo(f"\n{label} {node.path}/")
    click.echo(f"  {node.description}")

    # Show simulation metadata
    if node.node_type == "simulation" and node.metadata:
        box = node.metadata.get("boxsize")
        cosmo = node.metadata.get("cosmology")
        nsnap = node.metadata.get("num_snapshots")
        if box and isinstance(box, (int, float)) and float(box) > 0:
            click.echo(f"  Box size:     {box}")
        if cosmo and str(cosmo) != "unknown":
            click.echo(f"  Cosmology:    {cosmo}")
        if nsnap:
            click.echo(f"  Snapshots:    {nsnap}")
        if node.metadata.get("is_subbox"):
            parent = node.metadata.get("parent_simulation")
            if parent:
                click.echo(f"  Parent sim:   {parent}")

    # List children
    children = node.list_children()
    if not children:
        if node.node_type == "dataset" and node.url:
            click.echo(f"\n  Download URL: {node.url}")
        elif node.node_type != "dataset":
            click.echo(f"\n  (no children)")
        return

    items = list(children.items())
    for child_name, child in items:
        if child.node_type == "dataset":
            # Dataset: show URL and optional download path
            line = f"  {child_name}  → {child.url}"
            if child.download_relpath:
                line += f"  [→ {child.download_relpath}]"
            click.echo(line)
        else:
            count = child.child_count
            loaded = child.is_loaded()
            count_str = f" ({count})" if count > 0 else ""
            loaded_str = "" if loaded else " [lazy]"
            click.echo(f"  {child_name}/{count_str}{loaded_str}  — {child.description}")

    if node.node_type == "group" and node.is_loaded():
        total = sum(
            c.child_count
            for c in children.values()
            if c.node_type != "dataset"
        )
        click.echo(f"\n  {len(children)} item(s). Use 'source list {path}/<name>' to drill down.")


@source_cmd.command("info")
@click.argument("path")
def source_info(path: str) -> None:
    """Show detailed info about a source tree node."""
    reg = Registry()
    node = reg.get_node(path)
    if node is None:
        click.echo(f"Path not found: {path!r}")
        raise SystemExit(1)

    click.echo(f"Path:        {node.path}/")
    click.echo(f"Type:        {node.node_type}")
    click.echo(f"Description: {node.description}")

    if node.node_type == "dataset" and node.url:
        click.echo(f"URL:         {node.url}")

    if node.auth is not None:
        auth = node.auth
        click.echo(f"Auth:        {auth.type if hasattr(auth, 'type') else 'yes'}")

    children = node.list_children()
    if children:
        click.echo(f"Children:    {len(children)}")
        items = list(children.items())
        for child_name, child in items[:30]:
            click.echo(f"  - {child_name}  ({child.node_type})")
        if len(items) > 30:
            click.echo(f"  ... and {len(items) - 30} more")
    else:
        click.echo(f"Children:    none")


@source_cmd.command("discover")
@click.argument("path", required=False, default="")
def source_discover(path: str) -> None:
    """Force lazy-load a node's children.

    \b
    Example:
      cosmo-dl source discover TNG         # load TNG sub-groups
      cosmo-dl source discover TNG/TNG50   # load TNG50 simulations
    """
    reg = Registry()
    if not path:
        click.echo("Usage: cosmo-dl source discover <path>")
        return

    node = reg.get_node(path)
    if node is None:
        click.echo(f"Path not found: {path!r}")
        raise SystemExit(1)

    if node.is_loaded():
        click.echo(f"{path}/ is already loaded ({len(node.list_children())} children).")
        return

    click.echo(f"Loading {path}/ ...")
    children = node.list_children()
    loaded = node.is_loaded()
    click.echo(f"Loaded {len(children)} child(ren). Loaded: {loaded}")
