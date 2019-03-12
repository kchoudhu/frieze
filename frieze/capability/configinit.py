#!/usr/bin/env python3

__all__ = ['ConfigInit', 'ConfigFile', 'ConfigGenFreeBSD']

import collections
import enum
import importlib
import io
import os
import tarfile

from openarc.exception import OAError

###### Some other definitions
from ..osinfo import HostOS, OSFamily, TunableType, Tunable
from ..hostproperty import HostProperty

class ConfigFile(enum.Enum):
    # Commands executed before config payload delivered
    PRE_COMMAND_LIST  = 'pre_cmdlist'
    # Configuration payload
    RC_CONF           = '/etc/rc.conf.local'
    RC_LOCAL          = '/etc/rc.local'
    BOOT_LOADER       = '/boot/loader.conf.local'
    SYSCTL_CONF       = '/etc/sysctl.conf.local'
    # Commands executed after config payload delivered
    POST_COMMAND_LIST = 'post_cmdlist'

class ConfigGenFreeBSD(object):
    def __init__(self, host):
        self.host = host
        self.cfg  = {}

    @property
    def intermediate_representation(self):
        """Generate an intermediate representation that is suitable for output"""
        from .._core import RoutingStyle, NetifType, FIB
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

            service = getattr(importlib.import_module('frieze.capability'), capability.service)()

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
            knob = prop.name
            if qualifiers:
                knob = f"{knob}_{'_'.join(qualifiers)}"

            return {
                ConfigFile.RC_CONF : {
                    knob : value
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
        self.cfg[ConfigFile.PRE_COMMAND_LIST] = []
        install_pkgs = [c.package for c in self.host.capability if c.package]
        self.cfg[ConfigFile.PRE_COMMAND_LIST].append('yes | pkg install '+ ' '.join(install_pkgs))

        # What about those tunables!
        for tunable in self.host.sysctl:
            dict_merge(self.cfg, gen_sysctl_config(tunable))

        # Merge in capability information
        for capability in self.host.capability:
            dict_merge(self.cfg, gen_capability_config(capability))

        # Set a hostname
        dict_merge(self.cfg, gen_property_config(HostProperty.hostname, value=self.host.fqdn))

        # Networking
        cloned_ifaces=[]
        for iface in self.host.net_iface:
            if iface.routingstyle==RoutingStyle.DHCP:
                value = 'DHCP'
            elif iface.routingstyle==RoutingStyle.STATIC:
                value = 'inet %s netmask %s' % (iface.ip4, iface.netmask)
                if iface.type==NetifType.VLAN:
                    value += ' vlan %d vlandev %s' % (iface.deployment.vlanid, iface.vlanhost.name)
                    cloned_ifaces.append(iface.name)
            dict_merge(self.cfg, gen_property_config(HostProperty.ifconfig, iface.name, value=value))
        if cloned_ifaces:
            dict_merge(self.cfg, gen_property_config(HostProperty.cloned_interfaces, value=' '.join(cloned_ifaces)))

        # Flatten rc.local into an array of commands to be executed
        try:
            self.cfg[ConfigFile.RC_LOCAL] = [v for k, v in self.cfg[ConfigFile.RC_LOCAL].items()]
        except KeyError:
            pass

        # Add post processing
        be_name = self.host.domain.version_name.lower().replace(' ', '_')
        self.cfg[ConfigFile.POST_COMMAND_LIST] = [
            f'bectl create {be_name}',
            f'bectl activate {be_name}',
            f'shutdown -r now'
        ]

        return self.cfg

class ConfigInit(object):
    def __init__(self, cfgen):
        self.cfgen = cfgen

    def generate(self, targetdir=None):
        """Return a configinit compatible representation of a configuration,
        either by parsing {cfgen}, or reading contents of {directory} into a
        tarball"""
        tarout = io.BytesIO()
        with tarfile.open(fileobj=tarout, mode="w") as tar:
            if self.cfgen:
                # This proceeds in steps:
                # 1. Normalize cfgen to a dict of filenames, payloads and permissions (omatrix)
                omatrix = {}
                for i, (tgt_file, payload) in enumerate(self.cfgen.items()):

                    # Normalized archive file name
                    src_file = tgt_file.value if isinstance(tgt_file, ConfigFile) else tgt_file
                    if src_file[0]=='/':
                        src_file = src_file[1:]
                    src_file = src_file.replace('/', '_')
                    arc_file = f'{i:05}-{src_file}'

                    # Archive file contents
                    if isinstance(tgt_file, ConfigFile):
                        # Data is coming in structured
                        if type(payload)==dict:
                            omatrix[arc_file] = f'>{tgt_file.value}\n'
                            for k, v in payload.items():
                                omatrix[arc_file] += f'{k}="{v}"\n'
                        elif type(payload)==list:
                            if tgt_file==ConfigFile.RC_LOCAL:
                                omatrix[arc_file] = f'>{tgt_file.value} 0744\n'
                                for v in payload:
                                    omatrix[arc_file] += f'{v}\n'
                            elif tgt_file in (ConfigFile.PRE_COMMAND_LIST, ConfigFile.POST_COMMAND_LIST):
                                for j, cmd in enumerate(payload):
                                    sequenced_arc_file = f'{i:05}-{j:05}-{src_file}'
                                    omatrix[sequenced_arc_file] = f'#!\n{cmd}'
                            else:
                                raise OAError("Not a supported filetype")
                    else:
                        # This is a straight config file, just output the payload. Header is assumed
                        omatrix[arc_file] = payload

                # 2. Materialize archive
                for file, content in omatrix.items():
                    tarinfo = tarfile.TarInfo(name=file)
                    payload = io.BytesIO()
                    tarinfo.size = payload.write(content.encode())
                    payload.seek(0)
                    tar.addfile(tarinfo=tarinfo, fileobj=payload)

        if targetdir:
            tarout.seek(0)
            tarfile.open(fileobj=tarout, mode='r').extractall(targetdir)

        return tarout.getvalue()
