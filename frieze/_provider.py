#!/usr/bin/env python3

__all__ = ['ExtCloud']

import vultr

class CloudInterface(object):
    def block_list(self):
        raise NotImplementedError("Implement in deriving Shim")

class VultrShim(CloudInterface):

    def __init__(self, apikey):
        self.api = vultr.Vultr(apikey)

    def block_list(self):
        return self.api.block.list()

class ExtCloud(object):

    def __init__(self, provider, apikey=None):

        # Import munging
        from ._core import Provider
        self.provdef = Provider

        #
        self.provider = provider
        self._api = {
            self.provdef.VULTR : VultrShim(apikey)
            # Add more providers as support is added
        }[self.provider]

    def __getattr__(self, attr):
        return getattr(self._api, attr, None)
