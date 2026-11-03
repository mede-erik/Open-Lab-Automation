"""Drivers for instruments that are not controlled with text commands.

A library model with ``"access": "driver"`` names its driver with ``"driver_id"``. A driver is
an object with ``call(function, args)``; the executor (``ola.instrument.Instrument``) hands it
the logical call. ``driver_for`` builds the driver of a model on an open connection.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .litevna import LiteVnaDriver

DRIVERS: Dict[str, Callable[[Any], Any]] = {"litevna": LiteVnaDriver}


def driver_for(library, model_id: str, transport) -> Optional[Any]:
    """The driver of a library model on ``transport``, or None if the model has no driver."""
    ref = library.find_model(model_id)
    if ref is None or ref.model.get("access") != "driver":
        return None
    factory = DRIVERS.get(ref.model.get("driver_id", ""))
    return factory(transport) if factory else None
