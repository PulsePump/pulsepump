from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files

import yaml


@dataclass(frozen=True)
class ModelBundle:
    key: str  # e.g. "boileau2015/cca"
    label: str  # human-readable, e.g. "boileau2015 / cca"
    project_name: str  # from YAML project_name field
    yaml_name: str  # e.g. "cca.yaml"
    inlet_name: str  # e.g. "cca_inlet.dat"
    vessels: tuple[str, ...]


def _parse_bundle(key: str, yaml_text: str) -> ModelBundle | None:
    data = yaml.safe_load(yaml_text)
    project = data.get("project_name", key.split("/")[-1])
    network = data.get("network", [])
    vessels = tuple(str(v.get("label", f"vessel_{i}")) for i, v in enumerate(network))
    if not vessels:
        return None
    yaml_name = f"{project}.yaml"
    inlet_name = f"{project}_inlet.dat"
    label = key.replace("/", " / ")
    return ModelBundle(
        key=key,
        label=label,
        project_name=project,
        yaml_name=yaml_name,
        inlet_name=inlet_name,
        vessels=vessels,
    )


def _walk(root, prefix: str = "") -> list[tuple[str, object]]:
    """Recursively yield (key, traversable) for every sub-package."""
    results: list[tuple[str, object]] = []
    for item in root.iterdir():
        name = item.name
        if name.startswith("_") or name.startswith("."):
            continue
        child_key = f"{prefix}/{name}" if prefix else name
        # Check if it's a directory (traversable) or a yaml file
        try:
            list(item.iterdir())
            results.extend(_walk(item, child_key))
        except NotADirectoryError, TypeError:
            if name.endswith(".yaml"):
                results.append((prefix, item))
    return results


def list_models() -> tuple[ModelBundle, ...]:
    pkg = files("pulsepump.openbf_models")
    bundles: list[ModelBundle] = []

    def recurse(traversable, key_parts: list[str]) -> None:
        yaml_files = []
        subdirs = []
        try:
            children = list(traversable.iterdir())
        except NotADirectoryError, TypeError:
            return
        for child in children:
            n = child.name
            if n.startswith("_") or n.startswith(".") or n.endswith(".jl"):
                continue
            if n.endswith(".yaml"):
                yaml_files.append(child)
            else:
                try:
                    list(child.iterdir())
                    subdirs.append((n, child))
                except NotADirectoryError, TypeError:
                    pass
        for yaml_file in yaml_files:
            try:
                text = yaml_file.read_text(encoding="utf-8")
                key = "/".join(key_parts)
                bundle = _parse_bundle(key, text)
                if bundle is not None:
                    bundles.append(bundle)
            except Exception:
                pass
        for name, subdir in subdirs:
            recurse(subdir, [*key_parts, name])

    recurse(pkg, [])
    return tuple(sorted(bundles, key=lambda b: b.key))
