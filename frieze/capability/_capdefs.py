__all__ = [
    'CapabilityTemplate',
    'bird',
    'dhclient',
    'dhcpd',
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

    # Knobs used by job system to adjust the operation of this capability. Knobs
    # not in this list cannot be set on the capability
    knobs = []

    def __init__(self):
        self.set_knobs = {}

    def setknob(self, knob, value):
        knobs = getattr(self, 'set_knobs', {})
        if not knobs:
            setattr(self, 'set_knobs', knobs)
        if knob in self.knobs:
            self.set_knobs[knob] = value
        else:
            raise OAError("[%s] is not a permitted knob for %s" % (knob, self.name))
        return self

    @property
    def setknobs_exist(self):
        return len(self.set_knobs)>0

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

class bird(CapabilityTemplate):
    jailable = False

class dhcpd(CapabilityTemplate):
    jailable = False
    knobs = [
        'ifaces'
    ]

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
