#!/usr/bin/env python3

__all__ = ['Domain', 'Site', 'Host', 'Netif', 'HostTemplate', 'set_domain',]

import enum

from openarc import staticproperty, oagprop
from openarc.dao import OADbTransaction
from openarc.graph import OAG_RootNode
from openarc.exception import OAGraphRetrieveError, OAError

####### Database structures, be nice

class OAG_Domain(OAG_RootNode):
    @property
    def is_unique(cls): return True

    @property
    def context(cls): return "frieze"

    @staticproperty
    def dbindices(cls): return {
        'domain' : [ ['domain'], True,  None ],
    }

    @staticproperty
    def streams(cls): return {
        'domain' : [ 'text',     str(), None ],
    }

    def add_site(self, sitename, shortname):
        try:
            site = OAG_Site((self, sitename), 'by_name')
        except OAGraphRetrieveError:
            site =\
                OAG_Site().db.create({
                    'domain'    : self,
                    'name'      : sitename,
                    'shortname' : shortname
                })

        return site

class OAG_Site(OAG_RootNode):
    @property
    def context(cls): return "frieze"

    @staticproperty
    def dbindices(cls): return {
        'name' : [ ['domain', 'name'], True, None ],
    }

    @staticproperty
    def streams(cls): return {
        'domain'    : [ OAG_Domain, True,  None ],
        'name'      : [ 'text',     str(), None ],
        'shortname' : [ 'text',     str(), None ],
    }

    def add_host(self, template, name, role):
        try:
            host = OAG_Host((self, name), 'by_name')
        except OAGraphRetrieveError:
            host =\
                OAG_Host().db.create({
                    'site' : self,
                    'cpus' : template.cpus,
                    'memory' : template.memory,
                    'bandwidth' : template.bandwidth,
                    'provider' : template.provider.value,
                    'name' : name,
                    'role' : role.value,
                })

            for i, iface in enumerate(template.interfaces):
                if i==0:
                    # Handle potential external interface
                    if OAG_Host.Role(host.role)==OAG_Host.Role.SITEBASTION:
                        host.add_iface(iface, OAG_NetIface.RoutingStyle.DHCP)
                    else:
                        host.add_iface(iface, OAG_NetIface.RoutingStyle.STATIC if self.bastion else OAG_NetIface.RoutingStyle.DHCP)
                else:
                    host.add_iface(iface, OAG_NetIface.RoutingStyle.STATIC)

        return host

    @property
    def bastion(self):
        sitebastions = self.clone()[-1].host.rdf.filter(lambda x: (OAG_Host.Role(x.role)==OAG_Host.Role.SITEBASTION))
        if sitebastions.size==1:
            return sitebastions
        else:
            return None

class OAG_NetIface(OAG_RootNode):
    class Type(enum.Enum):
        PHYSICAL    = 1
        OVPN_SERVER = 2
        OVPN_CLIENT = 3
        VLAN        = 4
        BRIDGE      = 5

    class RoutingStyle(enum.Enum):
        DHCP   = 1
        STATIC = 2

    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def dbindices(cls): return {
        'name' : [ ['host', 'name'], True, None ],
    }

    @staticproperty
    def streams(cls): return {
        'host'      : [ OAG_Host,     True,  None ],
        'name'      : [ 'text',       True,  None ],
        'type'      : [ 'int',        False, None ],
        'mac'       : [ 'text',       False, None ],
        'routing'   : [ 'int',        False, None ],
        'wireless'  : [ 'boolean',    True,  None ],
        # Interface is part of a bridge
        'bridge'    : [ OAG_NetIface, False, None ],
        # Interface is a vlan cloned off vlanhost
        'vlanhost'  : [ OAG_NetIface, False, None ]
    }

    @oagprop
    def vlans(self, **kwargs):
        if self.type==self.Type.PHYSICAL.value:
            return self.net_iface_vlanhost
        else:
            OAError("Non-physical interfaces can't clone vlans")

    @oagprop
    def bridge_members(self, **kwargs):
        if self.type==self.Type.BRIDGE.value:
            return self.net_iface_bridge
        else:
            OAError("Non-bridge interfaces can't have bridge members")

class OAG_Host(OAG_RootNode):
    class Provider(enum.Enum):
        DIGITALOCEAN = 1
        VULTR        = 2
        DC           = 3

    class Role(enum.Enum):
        SITEROUTER   = 1
        SITEBASTION  = 2
        COMPUTE      = 3
        STORAGE      = 4

    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def dbindices(cls): return {
        'name' : [ ['site', 'name'], True, None ],
    }

    @staticproperty
    def streams(cls): return {
        'site'      : [ OAG_Site, True, None ],
        'cpus'      : [ 'int',    True, None ],
        'memory'    : [ 'int',    True, None ],
        'bandwidth' : [ 'int',    True, None ],
        'provider'  : [ 'int',    True, None ],
        'name'      : [ 'text',   True, None ],
        'role'      : [ 'int',    True, None ],
    }

    @property
    def fqdn(self):
        return '%s.%s.%s' % (self.name, self.site.shortname, self.site.domain.domain)

    def add_iface(self, name, routing, type_=OAG_NetIface.Type.PHYSICAL, mac=str(), wireless=False):
        try:
            iface = OAG_NetIface((self, name), 'by_name')
        except OAGraphRetrieveError:
            iface =\
                OAG_NetIface().db.create({
                    'host'     : self,
                    'name'     : name,
                    'type'     : type_.value,
                    'mac'      : mac,
                    'routing'  : routing.value,
                    'wireless' : wireless,
                })
        return iface

    def add_clone_iface(self, name, type_, bridge_components):
        with OADbTransaction("Bridge creation"):
            clone = self.add_iface(name, type_=type_)
            for iface in bridge_components:
                if type_==OAG_NetIface.Type.BRIDGE:
                    iface.bridge = clone
                    iface.db.update()
                elif type_==OAG_NetIface.Type.VLAN:
                    clone.vlanhost = iface[-1]
                    clone.db.update()

        return clone

class HostTemplate(object):
    def __init__(self, cpus=None, memory=None, bandwidth=None, provider=None, interfaces=[]):
        self.cpus = cpus
        self.memory = memory
        self.bandwidth = bandwidth
        self.provider = provider
        self.interfaces = interfaces

####### Exportable friendly names go here

Host = OAG_Host
Netif = OAG_NetIface
Domain = OAG_Domain
Site = OAG_Site

####### User api goes here

def set_domain(domain):
    try:
        domain = OAG_Domain(domain, 'by_domain')
    except OAGraphRetrieveError:
        domain =\
            OAG_Domain().db.create({
                'domain' : domain
            })

    return domain
