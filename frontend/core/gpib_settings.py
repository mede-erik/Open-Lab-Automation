# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Where the GPIB adapters configured in *Tools > GPIB adapters* are kept.

The list of adapters (``ola.gpib_adapter.GpibAdapterConfig``) is saved as JSON in the application
settings (``QSettings('LabAutomation', 'App')``, key ``gpib_adapters``), so the tool and the
address editor of the instruments read the same configuration. The result of the last bus scan of
each adapter is kept in memory for the session: the address editor offers those instruments.
"""

import logging
from typing import Dict, List, Optional

from PyQt6.QtCore import QSettings

from ola.gpib_adapter import (
    BusDevice,
    GpibAdapterConfig,
    GpibError,
    check_unique_names,
    configs_from_json,
    configs_to_json,
)

SETTINGS_KEY = "gpib_adapters"
log = logging.getLogger(__name__)

_last_scan: Dict[str, List[BusDevice]] = {}


def _settings(settings: Optional[QSettings]) -> QSettings:
    return settings if settings is not None else QSettings("LabAutomation", "App")


def load_adapters(settings: Optional[QSettings] = None) -> List[GpibAdapterConfig]:
    """The configured adapters ([] if none, or if the saved list is damaged: it is logged)."""
    text = _settings(settings).value(SETTINGS_KEY, "", type=str)
    try:
        return configs_from_json(text)
    except GpibError as exc:
        log.error(f"GPIB adapters configuration not readable, ignored: {exc}")
        return []


def save_adapters(configs: List[GpibAdapterConfig], settings: Optional[QSettings] = None) -> None:
    """Save the adapters; ``GpibError`` [GPIB-006] if one is not valid (nothing is saved)."""
    for c in configs:
        c.validate()
    check_unique_names(configs)
    s = _settings(settings)
    s.setValue(SETTINGS_KEY, configs_to_json(configs))
    s.sync()


def adapters_or_default(settings: Optional[QSettings] = None) -> List[GpibAdapterConfig]:
    """The configured adapters, or a generic VISA board GPIB0 when none is configured (used only
    to write a GPIB address: it is never saved, so it never appears as a configured adapter)."""
    return load_adapters(settings) or [GpibAdapterConfig(profile="generic_visa")]


def remember_scan(adapter_name: str, devices: List[BusDevice]) -> None:
    """Keep the result of a bus scan of ``adapter_name`` for this session."""
    _last_scan[adapter_name] = list(devices)


def last_scan(adapter_name: str) -> List[BusDevice]:
    """The instruments found by the last scan of ``adapter_name`` in this session ([] if none)."""
    return list(_last_scan.get(adapter_name, []))


def forget_scans() -> None:
    """Drop every remembered scan (tests)."""
    _last_scan.clear()
