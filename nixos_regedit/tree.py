"""Option tree construction shared by the API and tests."""

from __future__ import annotations

from typing import Any


def option_segments(option_key: str, option: dict[str, Any]) -> list[str]:
    loc = option.get("loc")
    if isinstance(loc, list) and loc:
        return [str(part) for part in loc]
    return [part for part in option_key.split(".") if part]


def build_tree(options: dict[str, dict[str, Any]]) -> dict[str, Any]:
    root: dict[str, Any] = {"name": "NixOS", "path": "", "children": [], "optionKeys": []}
    index: dict[tuple[str, ...], dict[str, Any]] = {(): root}

    for option_key, option in sorted(options.items()):
        segments = option_segments(option_key, option)
        namespace = segments[:-1]
        path: list[str] = []
        for segment in namespace:
            path.append(segment)
            path_tuple = tuple(path)
            if path_tuple not in index:
                parent = index[tuple(path[:-1])]
                node = {
                    "name": segment,
                    "path": ".".join(path),
                    "children": [],
                    "optionKeys": [],
                }
                parent["children"].append(node)
                index[path_tuple] = node
        index[tuple(path)]["optionKeys"].append(option_key)

    _sort_tree(root)
    return root


def _sort_tree(node: dict[str, Any]) -> None:
    node["children"].sort(key=lambda child: child["name"].lower())
    for child in node["children"]:
        _sort_tree(child)
