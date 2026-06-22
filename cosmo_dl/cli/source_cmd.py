"""CLI command: source — browse the simulation source tree."""

from __future__ import annotations

import rich_click as click
from rich.console import Console
from rich.table import Table
from rich.tree import Tree

from cosmo_dl.registry.registry import Registry

console = Console()


def _status_str(node) -> str:
    """Return the status string for a node.

    - Empty string when already loaded or when the node has no lazy loader
      (i.e. it's a permanent leaf / informational entry like Auriga).
    - ``"lazy"`` when the node has a loader that hasn't been called yet.
    """
    if node.is_loaded():
        return ""
    if node._loader is not None:
        return "lazy"
    return ""


def _render_metadata(node) -> None:
    """Render common metadata fields for any node type.

    Shows ``data_page`` and ``download`` links for group/category nodes
    that have them (e.g. Auriga informational entry).
    """
    if not node.metadata:
        return

    data_page = node.metadata.get("data_page")
    download = node.metadata.get("download")

    if data_page and isinstance(data_page, str):
        console.print(f"  [dim]Data page:[/dim]   {data_page}")
    if download and isinstance(download, str):
        console.print(f"  [dim]Download:[/dim]    {download}")


def _build_tree(node, tree: Tree | None = None) -> Tree:
    """Recursively build a :class:`rich.tree.Tree` from a :class:`SourceNode`."""
    if tree is None:
        type_colors = {
            "group": "bright_blue",
            "category": "yellow",
            "simulation": "green",
            "dataset": "cyan",
        }
        color = type_colors.get(node.node_type, "white")
        tree = Tree(f"[bold {color}]{node.path}/[/bold {color}]")

    children = node.list_children()
    if not children:
        if node.node_type == "dataset" and node.url:
            tree.add(f"[dim]→[/dim] {node.url}")
        return tree

    # Sort: groups/categories/simulations first, then datasets
    items = sorted(
        children.items(),
        key=lambda kv: (0 if kv[1].node_type != "dataset" else 1, kv[0]),
    )

    for child_name, child in items:
        if child.node_type == "dataset":
            label = f"[cyan]{child_name}[/cyan]  [dim]→[/dim] {child.url}"
            tree.add(label)
        else:
            loaded = child.is_loaded()
            count = child.child_count
            count_str = f" [dim]({count})[/dim]" if count > 0 else ""
            lazy_str = (
                f" [dim]\\[{_status_str(child)}][/dim]"
                if not loaded and child._loader is not None
                else ""
            )

            type_icons = {
                "group": "📁",
                "category": "📂",
                "simulation": "🔬",
            }
            icon = type_icons.get(child.node_type, "")
            label = f"{icon} [bold]{child_name}/[/bold]{count_str}{lazy_str}  [dim]—[/dim] {child.description}"
            branch = tree.add(label)
            # Recursively expand loaded children
            if loaded and child.node_type != "dataset":
                _build_tree(child, branch)

    return tree


def _show_node_info(node) -> None:
    """Display metadata for a single node (simulation or dataset)."""
    type_colors = {
        "group": "bright_blue",
        "category": "yellow",
        "dataset": "cyan",
        "simulation": "green",
    }
    color = type_colors.get(node.node_type, "white")
    console.print(f"\n[{color}][{node.node_type}][/{color}] [bold]{node.path}/[/bold]")
    console.print(f"  {node.description}")

    _render_metadata(node)

    # Simulation-specific metadata
    if node.node_type == "simulation" and node.metadata:
        box = node.metadata.get("boxsize") or node.metadata.get("box_size")
        cosmo = node.metadata.get("cosmology")
        nsnap = node.metadata.get("num_snapshots")
        particles = node.metadata.get("particles")

        if box and isinstance(box, (int, float)) and float(box) > 0:
            console.print(f"  [dim]Box size:[/dim]     {box}")
        if particles:
            console.print(f"  [dim]Particles:[/dim]    {particles}")
        if cosmo and str(cosmo) != "unknown":
            console.print(f"  [dim]Cosmology:[/dim]    {cosmo}")
        if nsnap:
            console.print(f"  [dim]Snapshots:[/dim]    {nsnap}")
        if node.metadata.get("is_subbox"):
            parent = node.metadata.get("parent_simulation")
            if parent:
                console.print(f"  [dim]Parent sim:[/dim]   {parent}")


@click.command("source")
@click.argument("path", required=False, default="")
def source_cmd(path: str) -> None:
    """Browse simulation data sources.

    \b
    Examples:
      cosmo-dl source                 # show all root groups
      cosmo-dl source TNG             # show TNG sub-groups
      cosmo-dl source TNG/TNG50       # show TNG50 simulations
      cosmo-dl source TNG/TNG50/TNG50-1  # show file categories
    """
    reg = Registry()

    if not path:
        # Show root level as a table
        roots = reg.roots
        table = Table(title="Available Simulation Sources", border_style="dim")
        table.add_column("Source", style="bold green", no_wrap=True)
        table.add_column("Items", justify="right", style="dim")
        table.add_column("Description")
        table.add_column("Status", style="dim")

        for name in sorted(roots.keys()):
            root = roots[name]
            count = root.child_count
            count_str = str(count) if count > 0 else "—"
            table.add_row(f"{name}/", count_str, root.description, _status_str(root))

        console.print(table)
        console.print(
            f"\n  [dim]{len(roots)} source(s). Use [bold]source <name>[/bold] to explore.[/dim]"
        )
        return

    node = reg.get_node(path)
    if node is None:
        console.print(f"[red]Path not found:[/red] {path!r}")
        raise SystemExit(1)

    # Show node info
    _show_node_info(node)

    # List children
    children = node.list_children()
    if not children:
        if node.node_type == "dataset" and node.url:
            console.print(f"\n  [dim]Download URL:[/dim] {node.url}")
        elif node.node_type != "dataset":
            console.print("\n  [dim](no children)[/dim]")
        return

    console.print()
    tree = _build_tree(node)
    console.print(tree)

    if node.node_type == "group":
        loaded_children = [c for c in children.values() if c.node_type != "dataset"]
        console.print(
            f"\n  [dim]{len(loaded_children)} item(s). "
            f"Use [bold]source {path}/<name>[/bold] to drill down.[/dim]"
        )
