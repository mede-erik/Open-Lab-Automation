"""A valid set of efficiency parameters, shared by the tests.

The order of the list is the order chosen by the user: ``iout`` is first, so it is the innermost
(fastest) sweep and the first parameter to be set; ``vin`` is the second."""

import copy

INSTRUMENTS = ["psu1", "psu2", "daq1", "load1"]
IOUT, VIN, VAUX, IIN, VOUT = range(5)  # positions in the list below

_GOOD = {
    "variables": [
        {
            "name": "iout",
            "set": {"instrument": "load1", "call": "set_current_level"},
            "sweep": {"start": 0.5, "stop": 2.5, "points": 3},
            "reads": {"load": {"instrument": "load1", "call": "read_current"}},
        },
        {
            "name": "vin",
            "set": {"instrument": "psu1", "call": "set_voltage", "args": {"channel_number": 1}},
            "sweep": {"values": [9, 12, 15]},
            "reads": {
                "psu": {
                    "instrument": "psu1",
                    "call": "read_voltage",
                    "args": {"channel_number": 1},
                },
                "daq": {"instrument": "daq1", "call": "read_ch", "args": {"channels": "101"}},
            },
            "verify": {"read": "daq", "tol_rel": 0.01, "tol_abs": 0.02},
            "limits": {"min": 5, "max": 20},
        },
        {"name": "vaux", "set": {"instrument": "psu2", "call": "set_voltage"}, "value": 12},
        {
            "name": "iin",
            "reads": {
                "daq": {
                    "instrument": "daq1",
                    "call": "read_ch",
                    "args": {"channels": "102"},
                    "scale": 10,
                }
            },
        },
        {
            "name": "vout",
            "reads": {
                "daq": {"instrument": "daq1", "call": "read_ch", "args": {"channels": "103"}}
            },
        },
    ],
    "timing": {"settle_s": 8, "samples": 5, "interval_s": 10},
    "derived": {
        "pin": "vin@daq * iin@daq",
        "pout": "vout@daq * iout@load",
        "efficiency": "100 * pout / pin",
    },
    "startup": [{"instrument": "psu1", "call": "output_on"}],
    "shutdown": [{"instrument": "psu1", "call": "output_off"}],
}


def good():
    """A fresh deep copy that a test can modify."""
    return copy.deepcopy(_GOOD)
