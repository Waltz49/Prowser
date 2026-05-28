#!/usr/bin/env python3
"""Field specifications for dynamic image-generation dialogs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Literal, Optional, Tuple, Union

FieldKind = Literal["text", "int_slider", "float_slider", "bool", "choice", "seed"]


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
