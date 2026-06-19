# -*- coding: utf-8 -*-
"""Car type module.

Provides a minimal `CarType` class used by the package.
This file exists so `from .car_type import CarType` in
`core/__init__.py` can import successfully.
"""

class CarType:
    """Minimal placeholder for vehicle/car type representation."""

    def __init__(self, name=None):
        self.name = name

    def __repr__(self):
        return f"CarType({self.name!r})"
