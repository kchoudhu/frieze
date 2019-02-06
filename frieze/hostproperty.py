#!/usr/bin/env python3

__all__ = [
    'HostProperty'
]

import enum

class HostProperty(enum.Enum):
    hostname      = 1
    ifconfig      = 2
