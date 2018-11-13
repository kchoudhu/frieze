#!/usr/bin/env python3

__all__ = ['Domain', 'Site', 'Host', 'Netif', 'HostTemplate', 'set_domain',]

import enum
import ipaddress

from openarc import staticproperty, oagprop
from openarc.dao import OADbTransaction
from openarc.graph import OAG_RootNode
from openarc.exception import OAGraphRetrieveError, OAError

####### Database structures, be nice

class OAG_Domain(OAG_RootNode):
    @staticproperty
    def is_unique(cls): return True

    @staticproperty
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

    def assign_subnet(self, type_, iface=None):
        # Save a subnet for administration
        if type_==OAG_Subnet.Type.ROUTING:
            sid = '172.16.0'
        else:
            site_subnets = self.subnet.rdf.filter(lambda x: OAG_Subnet.Type(x.type)==OAG_Subnet.Type.SITE)

            if site_subnets.size==0:
                sid = '172.16.1'
            else:
                sid = '172.16.%d' % (int(site_subnets[-1].sid.split('.')[-1])+1)

        self.db.search()

        return\
            OAG_Subnet().db.create({
                'domain'        : self,
                'sid'           : sid,
                'mask'          : 24,
                'type'          : type_.value,
                'router'        : iface.host if iface else None,
                'routing_iface' : iface,
            })

    @property
    def routing_subnet(self):
        """Used to route traffic between sites"""
        return ipaddress.ip_network("172.16.0.0/24")

class OAG_Site(OAG_RootNode):
    @staticproperty
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

            for iface in template.interfaces:
                if iface[1]:
                    host.add_iface(iface[0], is_external=True)
                else:
                    host.add_iface(iface[0])

        return host

    @property
    def bastion(self):
        sitebastions = self.clone()[-1].host.rdf.filter(lambda x: x.is_bastion)
        if sitebastions.size==1:
            return sitebastions
        else:
            return None

    @property
    def compute_hosts(self):
        compute_hosts = self.clone()[-1].host.rdf.filter(lambda x: not x.is_bastion)
        if compute_hosts.size>0:
            return compute_hosts
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
        'host'        : [ OAG_Host,     True,  None ],
        'name'        : [ 'text',       True,  None ],
        'type'        : [ 'int',        False, None ],
        'mac'         : [ 'text',       False, None ],
        # Is connected to the internet
        'is_external' : [ 'boolean',    False, None ],
        'wireless'    : [ 'boolean',    True,  None ],
        # Interface is part of a bridge
        'bridge'      : [ OAG_NetIface, False, None ],
        # Interface is a vlan cloned off vlanhost
        'vlanhost'    : [ OAG_NetIface, False, None ],
        # Interface which routes traffic from this iface
        'routed_by'   : [ OAG_NetIface, False, None ],
    }

    @property
    def bird_enabled(self):
        return not self.is_external

    @oagprop
    def bridge_members(self, **kwargs):
        if self.type==self.Type.BRIDGE.value:
            return self.net_iface_bridge
        else:
            OAError("Non-bridge interfaces can't have bridge members")

    @property
    def broadcast(self):
        return self.routed_by.subnet[-1].broadcast if self.routed_by else None

    @property
    def dhcpd_enabled(self):
        return self.host.is_bastion and not self.is_external

    @property
    def gateway(self):
        return self.routed_by.subnet[-1].gateway if self.routed_by else None

    @property
    def routingstyle(self):
        if self.host.site.bastion:
            if self.host.is_bastion:
                if self.is_external:
                    return self.RoutingStyle.DHCP
                else:
                    return self.RoutingStyle.STATIC
            else:
                if self.is_external:
                    return self.RoutingStyle.STATIC
                else:
                    return self.RoutingStyle.DHCP
        else:
            if self.is_external:
                return self.RoutingStyle.DHCP
            else:
                return self.RoutingStyle.STATIC

    @oagprop
    def vlans(self, **kwargs):
        if self.type==self.Type.PHYSICAL.value:
            return self.net_iface_vlanhost
        else:
            OAError("Non-physical interfaces can't clone vlans")

class OAG_Subnet(OAG_RootNode):
    """Subnets are doled out on a per-domain basis and then assigned to
    assigned to a site."""
    class Type(enum.Enum):
        ROUTING = 1
        SITE    = 2

    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def dbindices(cls): return {
    }

    @staticproperty
    def streams(cls): return {
        'domain'        : [ OAG_Domain,   True,  None ],
        'sid'           : [ 'text',       str(), None ],
        'mask'          : [ 'int',        int(), None ],
        # what is this subnet used for?
        'type'          : [ 'int',        int(), None ],
        'router'        : [ OAG_Host,     False, None ],
        'routing_iface' : [ OAG_NetIface, False, None ]
    }

    @property
    def broadcast(self):
        return "%s.255" % self.sid

    @property
    def cidr(self):
        return "%s.0/%d" % (self.sid, self.mask)

    @property
    def gateway(self):
        return "%s.1"  % self.sid

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

    def add_iface(self, name, is_external=False, type_=OAG_NetIface.Type.PHYSICAL, mac=str(), wireless=False):
        try:
            iface = OAG_NetIface((self, name), 'by_name')
        except OAGraphRetrieveError:
            iface =\
                OAG_NetIface().db.create({
                    'host'        : self,
                    'name'        : name,
                    'type'        : type_.value,
                    'mac'         : mac,
                    'is_external' : is_external,
                    'wireless'    : wireless,
                })

            if not iface.is_external and type_==OAG_NetIface.Type.PHYSICAL:
                if self.is_bastion:
                    self.site.domain.assign_subnet(OAG_Subnet.Type.SITE, iface=iface)
                else:
                    # Add internal routing
                    if self.site.bastion:
                        # We're going to use crude techniques to reroute traffic for
                        # internial interfaces on compute hosts in sites with a bastion:
                        #
                        # The nth internal interface on a compute host is routed by
                        # the nth subnet on the sitebastion.
                        #
                        # If the nth subnet is not available on the sitebastion, this
                        # interface is to be left unrouted.
                        for host in self.site.compute_hosts:
                            for i, int_iface in enumerate(host.internal_ifaces):
                                try:
                                    int_iface.routed_by = self.site.bastion.routed_subnets[i].routing_iface
                                    int_iface.db.update()
                                except IndexError:
                                    pass
                    else:
                        # Whatever, there is no internal routing for this setup yet
                        pass

        return iface

    @property
    def internal_ifaces(self):
        return self.net_iface.clone().rdf.filter(lambda x: x.is_external is False)

    @property
    def is_bastion(self):
        return OAG_Host.Role(self.role)==OAG_Host.Role.SITEBASTION

    @property
    def routed_subnets(self):
        return self.subnet.clone()

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

        domain.assign_subnet(OAG_Subnet.Type.ROUTING)

    return domain
