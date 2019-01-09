#!/usr/bin/env python3

__all__ = ['ExtCloud']

import vultr

class CloudInterface(object):

    def block_create(self, location, size_gb, label=None):
        raise NotImplementedError("Implement in deriving Shim")

    def block_delete(self, subid):
        raise NotImplementedError("Implement in deriving Shim")

    def block_delete_mark(self, subid, label):
        raise NotImplementedError("Implement in deriving Shim")

    def block_list(self):
        raise NotImplementedError("Implement in deriving Shim")

class VultrShim(CloudInterface):

    def __init__(self, apikey):
        self.api = vultr.Vultr(apikey)

    def block_create(self, location, size_gb, label=None):
        rets = self.api.block.create(1, size_gb, label)
        return {
            'vsubid' : rets['SUBID']
        }

    def block_delete(self, subid):
        rets = self.api.block.delete(subid)
        return

    def block_delete_mark(self, subid, label):
        self.api.block.label_set(subid, label)

    def block_list(self):
        rets = self.api.block.list()
        return [{
            'vsubid' : ret['SUBID'],
            'label'  : ret['label'],
            'asset'  : ret
        } for ret in rets]

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
