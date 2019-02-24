#!/usr/bin/env python3

from . import base

from .base import *
from .package import *

__all__ = ['ConfigGenFreeBSD', 'ConfigGenLinux']
__all__.extend(base.__all__)
__all__.extend(package.__all__)

###### Some other definitions
import collections
import enum
import importlib
import os

from ..osinfo import HostOS, OSFamily, TunableType, Tunable
from ..hostproperty import HostProperty

class ConfigFile(enum.Enum):
    COMMAND_LIST = 'cmdlist'
    RC_CONF      = '/etc/rc.conf.local'
    RC_LOCAL     = '/etc/rc.local'
    BOOT_LOADER  = '/boot/loader.conf.local'
    SYSCTL_CONF  = '/etc/sysctl.conf.local'

class ConfigGenFreeBSD(object):
    def __init__(self, host):
        self.host = host
        self.cfg  = {}

    def generate(self):
        from .._core import RoutingStyle, FIB
        def gen_sysctl_config(dbsysctl):
            (file, knob, value) = {
                TunableType.BOOT    : ( ConfigFile.BOOT_LOADER,
                                        dbsysctl.tunable.sysctl,
                                        dbsysctl.value),
                TunableType.RUNTIME : ( ConfigFile.SYSCTL_CONF,
                                        dbsysctl.tunable.sysctl,
                                        dbsysctl.value),
                TunableType.KMOD    : ( ConfigFile.BOOT_LOADER,
                                       "%s_load" % dbsysctl.tunable.sysctl,
                                       "YES" if dbsysctl.value=='true' else "NO"),
            }[tunable.type]

            return { file : { knob : value } }

        def gen_capability_config(capability):
            rv = {
                ConfigFile.RC_CONF  : {},
                ConfigFile.RC_LOCAL : {},
            }

            knob     = "%s_enable" % capability.service
            knob_fib = "%s_fib" % capability.service

            rv[ConfigFile.RC_CONF] = {
                True : {knob : "YES"},
                False: {knob : "NO"},
                None : {},
            }[capability.start_rc]

            service = getattr(importlib.import_module(__name__), capability.service)()

            if capability.start_rc:
                if capability.fib==FIB.WORLD:
                    rv[ConfigFile.RC_CONF][knob_fib] = capability.fib.value
            else:
                if capability.start_local:
                    knob  = "%s_%s" % (capability.service, capability.id)
                    value = service.startcmd(self.host.os, capability.fib, capability.start_local_prms)
                    rv[ConfigFile.RC_LOCAL][knob] = value

            if capability.capability_knob:
                for cck in capability.capability_knob:
                    knob = '%s_%s' % (capability.service, cck.knob)
                    rv[ConfigFile.RC_CONF][knob] = cck.value

            # Generate configurations if present in resources
            rv = {**rv, **service.generate_cfg_files(self.host)}

            return rv

        def gen_property_config(prop, *qualifiers, value=None):
            return {
                ConfigFile.RC_CONF : {
                    '%s_%s' % (prop.name, '_'.join(qualifiers)) : value
                }
            }

        def dict_merge(dct, merge_dct):
            for k, v in merge_dct.items():
                if (k in dct and isinstance(dct[k], dict)
                        and isinstance(merge_dct[k], collections.Mapping)):
                    dict_merge(dct[k], merge_dct[k])
                else:
                    dct[k] = merge_dct[k]

        # Install packages to begin with
        self.cfg[ConfigFile.COMMAND_LIST] = []
        install_pkgs = [c.package for c in self.host.capability if c.package]
        self.cfg[ConfigFile.COMMAND_LIST].append('yes | pkg install '+ ' '.join(install_pkgs))

        # What about those tunables!
        for tunable in self.host.sysctl:
            dict_merge(self.cfg, gen_sysctl_config(tunable))

        # Merge in capability information
        for capability in self.host.capability:
            dict_merge(self.cfg, gen_capability_config(capability))

        # Set a hostname
        dict_merge(self.cfg, gen_property_config(HostProperty.hostname, value=self.host.fqdn))

        # Networking
        for iface in self.host.net_iface:
            if iface.routingstyle==RoutingStyle.DHCP:
                value = 'DHCP'
            elif iface.routingstyle==RoutingStyle.STATIC:
                value = 'inet %s netmask %s' % (iface.ip4, iface.netmask)
            dict_merge(self.cfg, gen_property_config(HostProperty.ifconfig, iface.name, value=value))

        # Flatten rc.local into an array of commands to be executed
        try:
            self.cfg[ConfigFile.RC_LOCAL] = [v for k, v in self.cfg[ConfigFile.RC_LOCAL].items()]
        except KeyError:
            pass

        return self

    def emit_output(self, targetdir):
        for i, (tgt_file, payload) in enumerate(self.cfg.items()):
            src_file = tgt_file.value if isinstance(tgt_file, ConfigFile) else tgt_file
            if src_file[0]=='/':
                src_file = src_file[1:]
            src_file = src_file.replace('/', '_')
            if isinstance(tgt_file, ConfigFile):
                # Data is coming in structured
                if type(payload)==dict:
                    src_file = '%05d-%s' % (i, src_file)
                    with open(os.path.join(targetdir, src_file), 'w') as f:
                        f.write('>%s\n' % tgt_file.value)
                        for k, v in payload.items():
                            f.write('%s="%s"\n' % (k, v))
                elif type(payload)==list:
                    if tgt_file==ConfigFile.RC_LOCAL:
                        src_file = '%05d-%s' % (i, src_file)
                        with open(os.path.join(targetdir, src_file), 'w') as f:
                            f.write('>%s\n' % tgt_file.value)
                            for v in payload:
                                f.write("%s\n" % v)
                    elif tgt_file==ConfigFile.COMMAND_LIST:
                        for j, cmd in enumerate(payload):
                            sequenced_src_file = '%05d-%05d-%s' % (i, j, src_file)
                            with open(os.path.join(targetdir, sequenced_src_file), 'w') as f:
                                f.write('#!\n%s' % cmd)
                    else:
                        raise OAError("Not a supported filetype")
            else:
                # This is a straight config file, just output the payload. Header is assumed
                src_file = '%05d-%s' % (i, src_file)
                with open(os.path.join(targetdir, src_file), 'w') as f:
                    f.write(payload)

class ConfigGenLinux(object):
    def __init__(self, host):
        pass

    def generate(self):
        raise NotImplementedError("No speaky penguin")
