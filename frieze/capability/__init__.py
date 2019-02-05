#!/usr/bin/env python3

from . import _capdefs

from ._capdefs import *

__all__ = ['ConfigGenFreeBSD', 'ConfigGenLinux']
__all__.extend(_capdefs.__all__)

###### Some other defintiions
import collections
import os
from ..osinfo import HostOS, OSFamily, TunableType

class ConfigGenFreeBSD(object):
    def __init__(self, host):
        self.host = host
        self.cfg  = {}

    def generate(self):
        from .._core import OAG_Capability, OAG_Sysctl

        def gen_sysctl_config(sysctl):
            (file, knob, value) = {
                TunableType.BOOT    : ('/boot/loader.conf',
                                        sysctl.tunable,
                                        sysctl.tunable),
                TunableType.RUNTIME : ('/etc/sysctl.conf',
                                        sysctl.tunable,
                                        sysctl.tunable),
                TunableType.KMOD    : ('/boot/loader.conf',
                                       "%s_load" % sysctl.tunable,
                                       "YES" if tunable.value=='true' else "NO"),
            }[tunable.type]

            return { file : { knob : value } }

        def gen_capability_config(capability):
            return {
                '/etc/rc.conf.local' : {
                    True : {'%s_enable' % capability.service : "YES" },
                    False: {'%s_enable' % capability.service : "NO" },
                    None : {},
            }[capability.enabled]}

        def dict_merge(dct, merge_dct):
            for k, v in merge_dct.items():
                if (k in dct and isinstance(dct[k], dict)
                        and isinstance(merge_dct[k], collections.Mapping)):
                    dict_merge(dct[k], merge_dct[k])
                else:
                    dct[k] = merge_dct[k]

        # Merge in capability information
        for capability in self.host.capability:
            dict_merge(self.cfg, gen_capability_config(capability))

        # What about those tunables!
        for tunable in self.host.sysctl:
            dict_merge(self.cfg, gen_sysctl_config(tunable))

        return self

    def emit_output(self, targetdir):
        with open(os.path.join(targetdir, 'MANIFEST'), 'w') as mfst:
            for tgt_file_name, payload in self.cfg.items():
                src_file_name = tgt_file_name.replace('/', '_')[1:]
                with open(os.path.join(targetdir, src_file_name), 'w') as f:
                    for k, v in payload.items():
                        f.write('%s="%s"\n' % (k, v))
                    mfst.write("%s %s\n" % (src_file_name, tgt_file_name))

class ConfigGenLinux(object):
    def __init__(self, host):
        pass

    def generate(self):
        raise NotImplementedError("No speaky penguin")
