#!/usr/bin/env python3

__all__ = [
    'OSCapabilityFactory'
    # Start exposing functionality
    'sshd']

from openarc import staticproperty
from .osinfo import HostOS, OSFamily

##### Config Factory
class ConfigGenFreeBSD(object):
    def __init__(self, capability):
        self.cap = capability

    def generate():
        pass

class ConfigGenLinux(object):
    def __init__(self, capability):
        pass

    def generate(self):
        raise NotImplementedError("No speaky penguin")

class ConfigFactory(object):
    """This generates the appropriate config generator"""
    def __init__(self, capability):
        self.capability = capability
        self.gencfg = {
            OSFamily.FreeBSD : ConfigGenFreeBSD(),
            OSFamily.Linux : ConfigGenLinux()
        }[host.os.family]

class Capability(object):
    """Applications derive from this"""
    def __init__(self, host):
        self.host = host
        self.status = None

    @property
    def config(self):
        if self._config is None:
            self._config = ConfigFactory(self).gencfg
        return self._config

    def disable(self):
        """Explicitly disable this capability"""
        self.status = False

    def enable(self):
        """Explicitly enable this capability"""
        self.status = True

    @staticproperty
    def jailable(cls): return True

    @staticproperty
    def name(cls): return cls.__name__

class FreeBSDCapabilities(object):
    """This is a collection of capabilities possessed by a runnale unit.
    Subclass as needed -- or use outright"""
    def __init__(self, host):
        self.host = host
        self._capabilities = []

        # Use this to put the capability on the generator
        def init_cap(cap):
            ccap = getattr(self, cap.name, None)
            if not ccap:
                ncap = cap(host)
                setattr(self, cap.name, ncap)
                if not [c for c in self._capabilities if c.name==cap.name]:
                    self._capabilities.append(ncap)

        # Add in our default capabilities
        init_cap(sshd)

    def add(self, capability):
        self._capabiltiies.append(capability)

class OSCapabilityFactory(object):

    def __init__(self, host):
        self.capabilities = {
            # Resist the temptation to key this by OSFamily.
            #
            # Remember that capabilities can differ between distro versions.
            # We are using the base class for now because we support so few
            # versions; as time goes by and versions diverge, this will change.
            HostOS.FreeBSD_11_2: FreeBSDCapabilities(host),
            HostOS.FreeBSD_12_0: FreeBSDCapabilities(host)
            # Add more operating systems here as needed (Linux, Windows etc)
        }[host.os]

##### A few example capabilities
class sshd(Capability): pass
