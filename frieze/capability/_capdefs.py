__all__ = [
    'CapabilityTemplate',
    'linux',
    'nginx',
    'openrelayd',
    'postgres',
    'sshd',
    'zfs',
]

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

class sshd(CapabilityTemplate):
    name   = 'sshd'

class zfs(CapabilityTemplate):
    name   = 'zfs'

class linux(CapabilityTemplate):
    name   = 'linux'

class nginx(CapabilityTemplate):
    name   = 'nginx'
    cores  =  0.5
    memory =  512

class openrelayd(CapabilityTemplate):
    name   = 'openrelayd'
    cores  =  0.25
    memory =  512

class postgres(CapabilityTemplate):
    name   = 'postgres'
    cores  =  1
    memory =  1024
    mounts = [('wal', 10), ('data', 10), ('extra', 10)]
