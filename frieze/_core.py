__all__ = ['FriezeDomain', 'set_domain',]

from enum import Enum
from openarc import staticproperty, oagprop
from openarc.graph import OAG_RootNode
from openarc.exception import OAGraphRetrieveError

####### Database structures, be nice

class OAG_FriezeDomain(OAG_RootNode):
    @property
    def context(self): return "frieze"

    @staticproperty
    def dbindices(cls): return {
        'domain' : [ ['domain'], True,  None ],
    }

    @staticproperty
    def streams(cls): return {
        'domain' : [ 'text',     str(), None ],
    }

####### Exportable friendly names go here

FriezeDomain = OAG_FriezeDomain

####### User api goes here

def set_domain(domain):
    try:
        domain = OAG_FriezeDomain(domain, 'by_domain')
    except OAGraphRetrieveError:
        domain =\
            OAG_FriezeDomain().db.create({
                'domain' : domain
            })

    return domain
