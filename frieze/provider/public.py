__all__ = [
    'ExtCloud',
    'CloudProvider',
    'Location'
]

import enum

class CloudProvider(enum.Enum):
    DIGITALOCEAN = 1
    VULTR        = 2
    DC           = 3

class Location(enum.Enum):
    NY           = 1
    LONDON       = 2

class ExtCloud(object):

    def __init__(self, provider, apikey=None):

        # Import munging
        from ._shim_vultr import VultrShim

        self.provider = provider
        self._api = {
            CloudProvider.VULTR : VultrShim(apikey)
            # Add more providers as support is added
        }[self.provider]

    def __getattr__(self, attr):
        return getattr(self._api, attr, None)
