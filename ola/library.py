"""Qt-free access to the instrument library and to the call schemas.

The library (``instruments_lib.json``) says, for every instrument, how each logical call is
implemented; the schemas (``schema/*.json`` next to the library) say what every logical call
means (argument names, types, units, logical values). This module only loads and resolves
data, it does no I/O with instruments.
"""

from __future__ import annotations

import copy
import glob
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def deep_merge(base: Any, patch: Any) -> Any:
    """Return a copy of ``base`` with ``patch`` merged in (dicts merge, others are replaced)."""
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return copy.deepcopy(patch)
    merged = copy.deepcopy(base)
    for key, value in patch.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def resolve_model_commands(series: Dict[str, Any], model: Dict[str, Any]) -> Dict[str, Any]:
    """Build the command set of one model from its series.

    Starts from the series ``common_scpi_commands`` and applies the model ``scpi_commands``,
    one entry per call name:

    * a full definition (has ``set``, ``query``, ``driver``) replaces the series command;
    * ``null`` removes the call: the model does not support it;
    * ``{"patch": {...}}`` deep-merges the fields into the series command (the call must exist
      in the series, otherwise the patch is ignored with a warning).
    """
    commands = copy.deepcopy(series.get("common_scpi_commands", {}))
    for name, definition in (model.get("scpi_commands") or {}).items():
        if definition is None:
            commands.pop(name, None)
        elif (
            isinstance(definition, dict)
            and "patch" in definition
            and not ({"set", "query", "driver"} & set(definition))
        ):
            if name in commands:
                commands[name] = deep_merge(commands[name], definition["patch"])
            else:
                log.warning(
                    "Model %s: cannot patch '%s', not defined in the series", model.get("id"), name
                )
        else:
            commands[name] = copy.deepcopy(definition)
    return commands


def load_schemas(schema_dir: str) -> Dict[str, Dict[str, Any]]:
    """Load every ``*.json`` call schema of a directory, keyed by library category."""
    schemas: Dict[str, Dict[str, Any]] = {}
    for path in sorted(glob.glob(os.path.join(schema_dir, "*.json"))):
        with open(path, encoding="utf-8") as f:
            schema = json.load(f)
        schemas[schema["category"]] = schema
    return schemas


@dataclass(frozen=True)
class ModelRef:
    """A model found in the library, with the category and the series it belongs to."""

    category: str
    series: Dict[str, Any]
    model: Dict[str, Any]

    @property
    def model_id(self) -> str:
        """The library id of the model, e.g. ``OSC_Siglent_SDS824X_HD``."""
        return self.model.get("id", "")


class Library:
    """The instrument library plus the call schemas of its categories."""

    def __init__(
        self,
        categories: Dict[str, List[Dict[str, Any]]],
        schemas: Optional[Dict[str, Dict[str, Any]]] = None,
        schema_version: Optional[int] = None,
    ):
        self.categories = categories
        self.schemas = schemas or {}
        self.schema_version = schema_version

    @classmethod
    def load(cls, library_path: str, schema_dir: Optional[str] = None) -> "Library":
        """Load ``instruments_lib.json`` and, by default, ``schema/*.json`` next to it."""
        with open(library_path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "instrument_library" in data:
            categories = data["instrument_library"]
            version = data.get("schema_version")
        else:
            categories, version = data, None
        schema_dir = schema_dir or os.path.join(
            os.path.dirname(os.path.abspath(library_path)), "schema"
        )
        return cls(categories, load_schemas(schema_dir), version)

    def find_model(self, model_id: str) -> Optional[ModelRef]:
        """The model with this library id, or None."""
        for category, series_list in self.categories.items():
            if not isinstance(series_list, list):
                continue
            for series in series_list:
                for model in series.get("models", []) or []:
                    if model.get("id") == model_id:
                        return ModelRef(category, series, model)
        return None

    def resolve_model_id(self, identifier: str) -> Optional[str]:
        """Return the library id of a model given its id, model code or name (project files
        sometimes store the model code instead of the id)."""
        for key in ("id", "model", "name"):
            for series_list in self.categories.values():
                if not isinstance(series_list, list):
                    continue
                for series in series_list:
                    for model in series.get("models", []) or []:
                        if model.get(key) == identifier:
                            return model.get("id")
        return None

    def serial_settings(self, model_id: str) -> Dict[str, Any]:
        """Serial (RS-232) settings the library gives for a model: baud, data_bits, parity,
        stop_bits, flow_control, write/read termination. Empty if the library has none."""
        ref = self.find_model(model_id)
        if ref is None:
            return {}
        for conn in ref.model.get("interface", {}).get("supported_connection_types", []):
            for transport in conn.get("transports", []) or []:
                if transport.get("kind") == "serial":
                    return {
                        k: v for k, v in transport.items() if k not in ("kind", "factory_defaults")
                    }
        return {}

    def commands(self, model_id: str) -> Optional[Dict[str, Any]]:
        """The command set of a model (series commands with the model overrides), or None."""
        ref = self.find_model(model_id)
        return resolve_model_commands(ref.series, ref.model) if ref else None

    def schema(self, category: str) -> Optional[Dict[str, Any]]:
        """The call schema of a library category (``None`` if the category has none)."""
        return self.schemas.get(category)
