# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Cards of kinds the registry of components no longer has (antenna, filter, other), written the
way the earlier version wrote them, for the tests of the move to the archive of the DUTs."""

import time
from typing import Any, Mapping, Optional

from ola.assets import Asset, AssetRegistry

LEGACY_PREFIXES = {"antenna": "ANT", "filter": "FLT", "other": "DUT"}


def add_legacy(
    registry: AssetRegistry,
    kind: str,
    name: str,
    description: str = "",
    attributes: Optional[Mapping[str, Any]] = None,
    **fields: Any,
) -> Asset:
    """Add a card of an old kind to the registry, with the next code of its prefix, and save."""
    prefix = LEGACY_PREFIXES[kind]
    registry.counters[prefix] = registry.counters.get(prefix, 0) + 1
    card = Asset(
        id=f"{prefix}-{registry.counters[prefix]:04d}",
        kind=kind,
        name=name,
        description=description,
        attributes=dict(attributes or {}),
        created=time.strftime("%Y-%m-%d"),
        **fields,
    )
    registry.assets.append(card)
    registry.save()
    return card
