#!/usr/bin/env python3
"""Field specifications and grouped layouts for image-generation dialogs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Callable, List, Literal, Optional, Tuple, Union

if TYPE_CHECKING:
    from imagegen_plugins.image_gen_registry import ImageGenModelPlugin

FieldKind = Literal["text", "int_slider", "float_slider", "bool", "choice", "seed"]
FieldLayoutKind = Literal[
    "column",
    "row",
    "labeled",
    "bool_run",
    "seed_row",
    "steps_quant_row",
    "prompt_block",
]

FieldLayoutBuilder = Callable[
    ["ImageGenModelPlugin", dict[str, Any], int],
    Tuple["FieldNode", ...],
]


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: FieldKind
    default: Any = None
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    step: Optional[Union[int, float]] = None
    choices: Optional[Tuple[Any, ...]] = None
    required: bool = False
    bool_label_override: Optional[str] = None
    reset_default: Optional[Any] = None


@dataclass(frozen=True)
class FieldGroup:
    layout: FieldLayoutKind
    label: Optional[str] = None
    children: Tuple["FieldNode", ...] = ()


FieldNode = Union[FieldSpec, FieldGroup]


def flatten_field_specs(nodes: Tuple[FieldNode, ...]) -> List[FieldSpec]:
    """Depth-first list of leaf FieldSpec entries (for validation / EXIF import)."""
    out: List[FieldSpec] = []
    for node in nodes:
        if isinstance(node, FieldSpec):
            out.append(node)
        else:
            out.extend(flatten_field_specs(node.children))
    return out


def resolve_field_nodes(
    nodes: Tuple[FieldNode, ...],
    values: dict[str, Any],
) -> Tuple[FieldNode, ...]:
    """Return a tree with each FieldSpec.default taken from values when present."""
    resolved: List[FieldNode] = []
    for node in nodes:
        if isinstance(node, FieldSpec):
            default = values.get(node.key, node.default)
            if node.kind in ("int_slider", "seed"):
                try:
                    default = int(default)
                except (TypeError, ValueError):
                    default = node.default
            elif node.kind == "float_slider":
                try:
                    default = float(default)
                except (TypeError, ValueError):
                    default = node.default
            elif node.kind == "bool":
                default = bool(default)
            elif node.kind == "text":
                default = str(default or "")
            resolved.append(replace(node, default=default))
        else:
            resolved.append(
                FieldGroup(
                    layout=node.layout,
                    label=node.label,
                    children=resolve_field_nodes(node.children, values),
                )
            )
    return tuple(resolved)


def resolve_plugin_field_layout(
    plugin: "ImageGenModelPlugin",
    values: dict[str, Any],
    *,
    effective_max_side: int,
) -> Tuple[FieldNode, ...]:
    """Build resolved field tree for a plugin from its layout builder."""
    builder = plugin.field_layout_builder
    if builder is None:
        raise ValueError(
            f"Plugin {plugin.plugin_id!r} has no field_layout_builder"
        )
    raw = builder(plugin, values, effective_max_side)
    return resolve_field_nodes(raw, values)
