__all__ = [
    'nginx',
    'openrelayd',
    'postgres'
]

from .base import CapabilityTemplate

class nginx(CapabilityTemplate):
    cores  =  0.5
    memory =  512

class openrelayd(CapabilityTemplate):
    cores  =  0.25
    memory =  512

class postgres(CapabilityTemplate):
    cores  =  1
    memory =  1024
    mounts = [('wal', 10), ('data', 10), ('extra', 10)]
