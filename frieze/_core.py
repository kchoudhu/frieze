#!/usr/bin/env python3

__all__ = ['FriezeDomain', 'set_domain',]

from enum import Enum
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

    def add_site(self, sitename):
        try:
            site = OAG_FriezeSite((self, sitename), 'by_name')
        except OAGraphRetrieveError:
            site =\
                OAG_FriezeSite(initprms={
                    'domain'   : self,
                    'sitename' : sitename,
                })

        return site

class OAG_Site(OAG_RootNode):
    @property
    def context(cls): return "frieze"

    @staticproperty
    def dbindices(cls): return {
        'name' : [ ['domain','sitename'], True, None ],
    }

    @staticproperty
    def streams(cls): return {
        'domain'   : [ OAG_FriezeDomain, True,  None ],
        'sitename' : [ 'text',           str(), None ]
    }

####### Exportable friendly names go here

Domain = OAG_FriezeDomain
Site = OAG_FriezeSite

####### User api goes here

def set_domain(domain):
    try:
        domain = OAG_FriezeDomain(domain, 'by_domain')
    except OAGraphRetrieveError:
        domain =\
            OAG_FriezeDomain(initprms={
                'domain' : domain
            })

    return domain
