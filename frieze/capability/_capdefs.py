__all__ = [
    'CapabilityTemplate',
    'gateway',
    'linux',
    'nginx',
    'openrelayd',
    'openssh',
    'postgres',
    'sshd',
    'zfs',
]

from openarc import staticproperty

class CapabilityTemplate(object):

    # Resource expectations.
    cores  = None
    memory = None
    # Mounts to be fed into the capability's container
    mounts = []
    # Ports to be redirected from outside
    ports = []
    # Config files that need to be set in the container
    config = []
    # The site in which we would like this cability to be run. None for any site.
    affinity = None
    # Application can exist inside a jail
    jailable = True

    @staticproperty
    def name(cls):
        return cls.__name__

class gateway(CapabilityTemplate): pass

class sshd(CapabilityTemplate): pass

class openssh(CapabilityTemplate): pass

class zfs(CapabilityTemplate): pass

class linux(CapabilityTemplate): pass

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
