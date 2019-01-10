#!/usr/bin/env python3

__all__ = ['HostOS', 'Tunable']

import enum

class HostOS(enum.Enum):
    FreeBSD_11_2 = 1
    FreeBSD_12_0 = 2


class Tunable(enum.Enum):
    # F - FreeBSD
    # L - Linux
    F_HW_VTNET_CSUM_DISABLE = 1000
    F_NET_FIBS              = 2000



