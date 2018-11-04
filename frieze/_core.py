#!/usr/bin/env python3

__all__ = ['Domain', 'Site', 'Host', 'set_domain',]

import enum

from openarc import staticproperty, oagprop
from openarc.graph import OAG_RootNode
from openarc.exception import OAGraphRetrieveError

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

    def add_host(self, **hostprms):
        print(hostprms)
        try:
            site = OAG_Host((self, hostprms['name']), 'by_name')
        except OAGraphRetrieveError:
            site =\
                OAG_Host().db.create({
                    'site' : self,
                    'cpus' : hostprms['cpus'],
                    'memory' : hostprms['memory'],
                    'bandwidth' : hostprms['bandwidth'],
                    'provider' : hostprms['provider'].value,
                    'name' : hostprms['name'],
                    'role' : hostprms['role'].value,
                })
        return site

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

    @property
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


####### Exportable friendly names go here

Host = OAG_Host
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
