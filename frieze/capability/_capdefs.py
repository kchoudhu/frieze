__all__ = [
    'CapabilityTemplate',
    'dhclient',
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

    # The site in which we would like this capability to be run. None for any site.
    affinity = None

    # Application can exist inside a jail
    jailable = True

    @staticproperty
    def name(cls):
        return cls.__name__

    def startcmd(self, os, fib, *args):
        """Return command to be used when starting this capability without
        the system job management infrastructure"""
        from ..osinfo import OSFamily
        extra_prms = ' '.join(args)
        return {
            OSFamily.FreeBSD: "setfib %s service %s restart %s" % (fib.value, self.name, extra_prms)
        }[os.family]

## Service definitions

class dhclient(CapabilityTemplate):
    jailable = False

class gateway(CapabilityTemplate): pass

class linux(CapabilityTemplate): pass

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

class sshd(CapabilityTemplate): pass

class zfs(CapabilityTemplate): pass
