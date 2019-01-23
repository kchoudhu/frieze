#!/usr/bin/env python3

__all__ = [
    'ConfigFactory'
]

from openarc import staticproperty
from .osinfo import HostOS, OSFamily

##### Config Factory
class ConfigGenFreeBSD(object):
    def __init__(self):
        pass

    def generate():
        pass

class ConfigGenLinux(object):
    def __init__(self, capability):
        pass

    def generate(self):
        raise NotImplementedError("No speaky penguin")

class ConfigFactory(object):
    """This generates the appropriate config generator"""
    def __init__(self, host):
        self.capability = capability
        self.gencfg = {
            OSFamily.FreeBSD : ConfigGenFreeBSD(),
            OSFamily.Linux : ConfigGenLinux()
        }[host.os.family]
