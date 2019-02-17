__all__ = [
    'nginx',
    'openrelayd',
    'openssh',
    'postgres'
]

from .base import CapabilityTemplate

class nginx(CapabilityTemplate):
    cores  =  0.5
    memory =  512

class openrelayd(CapabilityTemplate):
    cores  =  0.25
    memory =  512

class openssh(CapabilityTemplate): pass

class postgres(CapabilityTemplate):
    cores  =  1
    memory =  1024
    mounts = [('wal', 10), ('data', 10), ('extra', 10)]

