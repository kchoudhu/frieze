__all__ = [
    # Utilities
    'CapabilityTemplate',
    'add',
    # Base services
    'bird',
    'dhclient',
    'dhcpd',
    'firstboot',
    'gateway',
    'jail',
    'linux',
    'named',
    'openssh',
    'pf',
    'pflate',
    'pflog',
    'resolvconf',
    'sshd',
    'trust',
    'zfs'
]

import frieze
import importlib
import io
import os
import sys
import tarfile

import mako.template
import pkg_resources as pkg

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

    # Package to install
    package = None

    # Knobs used by job system to adjust the operation of this capability. Knobs
    # not in this list cannot be set on the capability
    knobs = []

    # Resource directory (for internal bookkeeping)
    resource_path = 'frieze.capability.resources'

    def __init__(self):
        self.set_knobs = {}
        self.cmd_count = 0

    def next_cmd_cfg_name(self):
        cfg_name = f'{self.name}_cmd_{self.cmd_count}'
        self.cmd_count += 1
        return cfg_name

    def generate_cfg_files(self, host, __exclude__=[]):
        rv = {}
        __exclude__.append('__init__.py')
        __exclude__.append('__pycache__')
        try:
            cmd_cnt = 0
            cap_cfgs = pkg.resource_listdir(self.resource_path, self.name)
            for cfg in [cfg for cfg in cap_cfgs if cfg not in __exclude__]:
                cfg_raw = pkg.resource_string(f'{self.resource_path}.{self.name}', cfg)
                if cfg_raw[0:2]=='#!':
                    cfg_name = self.next_cmd_cfg_name()
                else:
                    cfg_1l = bytearray()
                    for b in cfg_raw:
                        if b=='\n'.encode()[0]:
                            break
                        cfg_1l.append(b)
                    cfg_name = bytes(cfg_1l[2:]).decode().split(' ')[0]

                try:
                    rv[cfg_name] = mako.template.Template(cfg_raw.decode()).render(host=host)
                except UnicodeDecodeError:
                    rv[cfg_name] = cfg_raw
        except FileNotFoundError:
            pass
        return rv

    @staticproperty
    def name(cls):
        return cls.__name__

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

    def startcmd(self, os, fib, *args):
        """Return command to be used when starting this capability without
        the system job management infrastructure"""
        from ..osinfo import OSFamily
        extra_prms = ' '.join(args)
        return {
            OSFamily.FreeBSD: "setfib %s service %s restart %s" % (fib.value, self.name, extra_prms)
        }[os.family]

def add(searchdir):
    """Add user-defined capabilities in searchdir. Pop up one directory and
    use import_modules"""
    canonical_path = os.path.expanduser(searchdir)
    sys.path.append(canonical_path)

    capmod = importlib.import_module('frieze.capability')
    modules = os.listdir(canonical_path)
    for module_name in modules:
        # Push module information into frieze.capability, and fix resource_path
        module = importlib.import_module(module_name)
        for m in dir(module):
            elem = getattr(module, m)
            if type(elem)==type and isinstance(elem(), CapabilityTemplate):
                setattr(capmod, elem.__name__, elem)
                setattr(elem, 'resource_path', f'{module_name}.resources')

    importlib.invalidate_caches()

## Service definitions

class bird(CapabilityTemplate):
    package = 'bird'
    jailable = False

class dhcpd(CapabilityTemplate):
    package = 'isc-dhcp44-server'
    jailable = False
    knobs = [
        'ifaces'
    ]

class dhclient(CapabilityTemplate):
    jailable = False

class firstboot(CapabilityTemplate):

    def generate_cfg_files(self, host, bootstrap=False):

        if bootstrap:
            exclude = []
        else:
            exclude = [
                'bootstrap.sh',
                'configinit.payload',
                'resetimage.sh',
            ]

        return super().generate_cfg_files(host, __exclude__=exclude)

    def generate_bootstrap_tarball(self):
        """Generate tarball of commands to be executed by frieze_configinit, which
        executes this payload on first boot"""
        rv = {
            frieze.capability.ConfigFile.PRE_COMMAND_LIST : [
                'sysrc -f /etc/rc.conf firstboot_pkgs_list="bash nano ca_root_nss openssh-portable"',
                'sysrc -f /etc/rc.conf sshd_enable="NO"',
                'sysrc -f /etc/rc.conf.local openssh_enable="YES"',
                'mkdir -p /usr/local/etc/ssh',
                'printf "TrustedUserCAKeys /usr/local/etc/ssh/ca.pub\nPasswordAuthentication no\nChallengeResponseAuthentication no\nPermitRootLogin prohibit-password\n" > /usr/local/etc/ssh/sshd_config'
            ]
        }

        return\
            frieze.capability.ConfigInit(rv)\
            .generate()\
            .decode()

class gateway(CapabilityTemplate): pass

class jail(CapabilityTemplate):

    def generate_cfg_files(self, host):
        """Generate regular files, and then add in fstabs for individual jails """
        rv = super().generate_cfg_files(host, __exclude__=['jail-fstab', 'jail-zfs-skeleton', 'jail-configinit'])

        pkg_name = 'frieze.capability.resources.%s' % self.name
        jail_zfs_template    = pkg.resource_string(pkg_name, 'jail-zfs-skeleton').decode()
        jail_fstab_template  = pkg.resource_string(pkg_name, 'jail-fstab').decode()
        jail_cfinit_template = pkg.resource_string(pkg_name, 'jail-configinit').decode()

        for container in host.containers:
            fstab_file = f'/usr/local/jails/{container.sysname}.fstab'
            rv[self.next_cmd_cfg_name()] = mako.template.Template(jail_zfs_template).render(container=container, host=host)
            rv[fstab_file] = mako.template.Template(jail_fstab_template).render(container=container, host=host)

            # Create config payload
            cfinit_file = f'{container.jaildir}/root/cfinit'
            rv[cfinit_file] = mako.template.Template(jail_cfinit_template).render(container=container, host=host)

        return rv

class linux(CapabilityTemplate): pass

class named(CapabilityTemplate):
    package = 'bind912'

    def generate_cfg_files(self, host):
        rv = {}
        zones = {}

        # Load some resources
        pkg_name = 'frieze.capability.resources.%s' % self.name
        zone_template        = pkg.resource_string(pkg_name, 'zone.db').decode()
        revzone_template     = pkg.resource_string(pkg_name, 'revzone.db').decode()
        named_local_template = pkg.resource_string(pkg_name, 'named.conf.local').decode()

        # Track reverse zones
        networks = dict()

        # Generate forward lookup files
        for site in host.site.domain.site:
            filename = "/usr/local/etc/namedb/dynamic/%s.db" % site.zone
            zones[site.zone] = filename
            rv[filename] = mako.template.Template(zone_template).render(zonecontainer=site, host=host)

            # Break forward lookups into class C's and assign revzones
            for dhost in site.host:
                try:
                    networks[dhost.revzone]
                except KeyError:
                    networks[dhost.revzone] = []
                networks[dhost.revzone].append({
                    'fqdn'   : dhost.fqdn,
                    'ip_ext' : dhost.ip4().split('.')[-1]
                })

        for deployment in host.site.domain.deployment:
            filename = "/usr/local/etc/namedb/dynamic/%s.db" % deployment.zone
            zones[deployment.zone] = filename
            rv[filename] = mako.template.Template(zone_template).render(zonecontainer=deployment, host=host)

            for container in deployment.containers:
                try:
                    networks[deployment.revzone]
                except KeyError:
                    networks[deployment.revzone] = []

                networks[deployment.revzone].append({
                    'fqdn'   : container.fqdn,
                    'ip_ext' : '.'.join(reversed(container.ip4().split('.')[2:]))
                })

        for nw, zonehosts in networks.items():
            filename = "/usr/local/etc/namedb/dynamic/%s.db" % nw
            zones[nw] = filename
            rv[filename] = mako.template.Template(revzone_template).render(revzone=nw, zonehosts=zonehosts, host=host)

        # Generate named.conf.local
        rv['/usr/local/etc/namedb/named.conf.local'] =\
            mako.template.Template(named_local_template).render(zones=zones)

        return {**rv, **super().generate_cfg_files(host, __exclude__=['zone.db', 'revzone.db', 'named.conf.local'])}

class pf(CapabilityTemplate): pass

class pflate(CapabilityTemplate): pass

class pflog(CapabilityTemplate): pass

class openssh(CapabilityTemplate):
    package = 'openssh-portable'

class resolvconf(CapabilityTemplate): pass

class sshd(CapabilityTemplate): pass

class trust(CapabilityTemplate):

    def generate_cfg_files(self, host):
        rv = {}

        # Generate trusts
        if type(host)!=frieze.Container:
            return rv

        from .server import TrustType, CertAction, CertFormat

        pkg_name = 'frieze.capability.resources.%s' % self.name
        crt_template  = pkg.resource_string(pkg_name, 'chain.crt')
        priv_template = pkg.resource_string(pkg_name, 'private.pem')

        cap = host.capability
        if cap.capability_alias and cap.capability_alias.is_external:
            print(f'======>Generating trusts for [{cap.fqdn}]')
            aliases = [ca.fqdn for ca in cap.capability_alias]
            cert =\
                cap.deployment.domain\
                .trust(trust_type=TrustType.LETSENCRYPT)\
                .issue_certificate(
                    aliases,
                    CertAction.REMOTE_ACCESS,
                    cert_format=CertFormat.PEM
                )

            rv[cap.truststore(pubkey=True)]  = mako.template.Template(crt_template).render(cap=cap, cert=cert)
            rv[cap.truststore(pubkey=False)] = mako.template.Template(priv_template).render(cap=cap, cert=cert)

        return rv

class zfs(CapabilityTemplate):

    def generate_cfg_files(self, host):

        rv = super().generate_cfg_files(host, __exclude__=['zpool-init'])

        pkg_name = 'frieze.capability.resources.%s' % self.name
        zpool_template = pkg.resource_string(pkg_name, 'zpool-init').decode()

        for bs in host.block_storage:
            try:
                rv[frieze.capability.ConfigFile.PRE_COMMAND_LIST]
            except KeyError:
                rv[frieze.capability.ConfigFile.PRE_COMMAND_LIST] = []
            rv[frieze.capability.ConfigFile.PRE_COMMAND_LIST].append(
                mako.template.Template(zpool_template).render(blockstore=bs, host=host)
            )

        return rv
