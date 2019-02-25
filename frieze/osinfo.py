#!/usr/bin/env python3

__all__ = ['OSFamily', 'HostOS', 'Tunable', 'TunableType', 'OSCapabilityFactory', 'Capability']

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

class TunableType(enum.Enum):
    BOOT    = 1
    RUNTIME = 2
    KMOD    = 3

class Tunable(enum.Enum):
    # FreeBSD range: 10000-19999
    # regression 10000-10049 (0)
    # sysctl     10050-10099 (0)
    # compat     10100-10199 (9)
    # user       10200-10399 (20)
    # machdep    10400-10799 (36)
    #            10800-10999 (reserved)
    # security   11000-11999 (82)
    # vm         12000-12999 (226)
    # debug      13000-13999 (305)
    # hw         14000-14999 (354)
    HW_VTNET_CSUM__DISABLE = 14000
    # vfs        15000-15999 (357)
    # net        16000-16999 (386)
    NET_ADD__ADDR__ALLFIBS = 16000
    NET_FIBS               = 16001
    # kern       17000-18999 (1034)
    # kmods      19000-19999 (1000)

    @property
    def family(self):
        return {
            1 : OSFamily.FreeBSD,
            2 : OSFamily.Linux
        }[self.value//10000]

    @property
    def sysctl(self):
        return self.name.replace('_', '.').replace('..', '_').lower()
