__all__ = [
    'CapabilityTemplate',
    'bird',
    'dhclient',
    'dhcpd',
    'gateway',
    'linux',
    'named',
    'openssh',
    'resolvconf',
    'sshd',
    'zfs',
]

import frieze

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

    def __init__(self):
        self.set_knobs = {}

    def generate_cfg_files(self, host, __exclude__=[]):
        rv = {}
        __exclude__.append('__init__.py')
        __exclude__.append('__pycache__')
        try:
            cap_cfgs = pkg.resource_listdir('frieze.capability.resources', self.name)
            for cfg in [cfg for cfg in cap_cfgs if cfg not in __exclude__]:
                cfg_raw = pkg.resource_string('frieze.capability.resources.%s' % self.name, cfg).decode()
                cfg_name = cfg_raw.split('\n')[0][2:].strip().split()[0]
                rv[cfg_name] = mako.template.Template(cfg_raw).render(host=host)
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

class gateway(CapabilityTemplate): pass

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
            rv[filename] = mako.template.Template(zone_template).render(zonecontainer=deployment, forward=True, host=host)

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

class openssh(CapabilityTemplate):
    package = 'openssh-portable'

class resolvconf(CapabilityTemplate): pass

class sshd(CapabilityTemplate): pass

class zfs(CapabilityTemplate): pass
