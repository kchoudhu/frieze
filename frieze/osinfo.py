#!/usr/bin/env python3

__all__ = ['OSFamily', 'HostOS', 'Tunable', 'OSCapabilityFactory', 'Capability']

import enum

class OSFamily(enum.Enum):
    FreeBSD = 1
    Linux   = 2

class HostOS(enum.Enum):
    FreeBSD_11_2 = 11120
    FreeBSD_12_0 = 11200

    @property
    def family(self):
        return {
            1 : OSFamily.FreeBSD,
            2 : OSFamily.Linux
        }[self.value//10000]

class Tunable(enum.Enum):
    # F - FreeBSD
    # L - Linux
    F_HW_VTNET_CSUM_DISABLE = 10001
    F_NET_FIBS              = 11001

    @property
    def family(self):
        return {
            1 : OSFamily.FreeBSD,
            2 : OSFamily.Linux
        }[self.value//10000]
