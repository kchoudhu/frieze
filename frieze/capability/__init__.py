#!/usr/bin/env python3

from . import _capdefs

from ._capdefs import *

__all__ = ['ConfigGenFreeBSD', 'ConfigGenLinux']
__all__.extend(_capdefs.__all__)

###### Some other defintiions
import os
from ..osinfo import HostOS, OSFamily, TunableType

class ConfigGenFreeBSD(object):
    def __init__(self, configurable):
        self.configurable = configurable

    def generate(self):
        from .._core import OAG_Capability, OAG_Sysctl

        def gen_capability_config():
            return {
                '/etc/rc.conf' : {
                    True : {'%s_enable' % self.configurable.service : "YES" },
                    False: {'%s_enable' % self.configurable.service : "NO" },
                    None : {},
            }[self.configurable.enabled]}

        def gen_sysctl_config():
            (file, knob, value) = {
                TunableType.BOOT    : ('/boot/loader.conf',
                                        self.configurable.tunable.sysctl,
                                        self.configurable.value),
                TunableType.RUNTIME : ('/etc/sysctl.conf',
                                        self.configurable.tunable.sysctl,
                                        self.configurable.value),
                TunableType.KMOD    : ('/boot/loader.conf',
                                       "%s_load" % self.configurable.tunable.sysctl,
                                       "YES" if self.configurable.value=='true' else "NO"),
            }[self.configurable.type]

            return { file : { knob : value } }

        return {
            OAG_Capability : gen_capability_config,
            OAG_Sysctl : gen_sysctl_config
        }[type(self.configurable)]()

    @staticmethod
    def emit_output(targetdir, cfg):
        with open(os.path.join(targetdir, 'MANIFEST'), 'w') as mfst:
            for tgt_file_name, payload in cfg.items():
                src_file_name = tgt_file_name.replace('/', '_')[1:]
                with open(os.path.join(targetdir, src_file_name), 'w') as f:
                    for k, v in payload.items():
                        f.write('%s="%s"\n' % (k, v))
                    mfst.write("%s %s\n" % (src_file_name, tgt_file_name))

class ConfigGenLinux(object):
    def __init__(self, capability):
        pass

    def generate(self):
        raise NotImplementedError("No speaky penguin")
