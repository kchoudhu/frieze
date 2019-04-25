__all__ = [
    # Utilities
    'HostTemplate',
    'add',
]

import frieze
import importlib
import io
import os
import sys

import frieze.capability
from frieze.osinfo import Tunable, TunableType

class HostTemplate(object):
    cores      = None
    memory     = None
    bandwidth  = None
    os         = None
    interfaces = [
        ('vtnet0', True, frieze.FIB.WORLD),
        ('vtnet1', False)
    ]
    sysctls    = [
        # Tunable-------------------------------------boot-----------------value
        # Do not checksum on VTNET interfaces
        (Tunable.HW_VTNET_CSUM__DISABLE,              TunableType.BOOT,    "1"),
        # We need two routing tables (one for internal, one for external)
        (Tunable.NET_FIBS,                            TunableType.BOOT,    "2"),
        # Allow ZFS inside jail
        (Tunable.SECURITY_JAIL_MOUNT__ZFS__ALLOWED,   TunableType.RUNTIME, "1"),
        # Allow devfs inside jail
        (Tunable.SECURITY_JAIL_MOUNT__DEVFS__ALLOWED, TunableType.RUNTIME, "1"),
        # Allow mounting inside jail
        (Tunable.SECURITY_JAIL_MOUNT__ALLOWED,        TunableType.RUNTIME, "1"),
        # Drop the transaction timeout to 1 second
        (Tunable.VFS_ZFS_TXG_TIMEOUT,                 TunableType.RUNTIME, "1"),
    ]
    caps       = [
        # cap------------------------enabled/disabled---external access
        (frieze.capability.sshd,     False,             False),
        (frieze.capability.openssh,  True,              True),
    ]

def add(searchdir):


    importlib.invalidate_caches()