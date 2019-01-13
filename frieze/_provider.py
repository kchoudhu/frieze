#!/usr/bin/env python3

__all__ = ['ExtCloud']

import enum
import vultr

from openarc.env import getenv

class CloudInterface(object):
    """Minimal functionality that needs to be implemented by a deriving shim
    to a cloud service"""
    def block_create(self, blockstore):
        raise NotImplementedError("Implement in deriving Shim")

    def block_delete(self, subid):
        raise NotImplementedError("Implement in deriving Shim")

    def block_delete_mark(self, subid, label):
        raise NotImplementedError("Implement in deriving Shim")

    def block_list(self, show_delete=False):
        raise NotImplementedError("Implement in deriving Shim")

    def server_create(self, host, snapshot=None, label=None):
        raise NotImplementedError("Implement in deriving Shim")

    def server_delete_mark(self, server):
        raise NotImplementedError("Implement in deriving Shim")

    def server_list(self, show_delete=False):
        raise NotImplementedError("Implement in deriving Shim")

    def snapshot_list(self):
        raise NotImplementedError("Implement in deriving Shim")

class VultrShim(CloudInterface):

    class Plan(enum.Enum):
        VPS_1_1_25    = 201
        VPS_1_2_40    = 202
        VPS_2_4_60    = 203
        VPS_4_8_100   = 204
        VPS_6_16_200  = 205
        VPS_8_32_300  = 206
        VPS_16_64_400 = 207
        VPS_24_96_800 = 208

    class Location(enum.Enum):
        NA_EWR        = 1
        EU_LHR        = 8

    class OS(enum.Enum):
        SNAPSHOT      = 164
        FreeBSD_12_0  = 327

    def bin_location(self, location):
        from ._core import Location as fLocation
        ret = None
        if location==fLocation.NY:
            ret = self.Location.NA_EWR
        elif location==fLocation.LDN:
            ret = self.Location.EU_LHR
        else:
            raise Exception("Location not supported by API")
        return ret.value

    def bin_host_plan(self, host):
        ret = None
        gb_memory = host.memory/1024
        if host.cpus == 1:
            ret = self.Plan.VPS_1_1_25 if gb_memory < 2 else self.Plan.VPS_1_2_40
        elif host.cpus == 2:
            ret = self.Plan.VPS_2_4_60
        elif 2 < host.cpus <= 4:
            ret = self.Plan.VPS_4_8_100
        elif 4 < host.cpus <= 6:
            ret = self.Plan.VPS_6_16_200
        elif 6 < host.cpus <= 8:
            ret = self.Plan.VPS_8_32_300
        elif 8 < host.cpus <= 16:
            ret = self.Plan.VPS_16_64_400
        elif 16 < host.cpus <=24:
            ret = self.Plan.VPS_24_96_800
        else:
            raise Exception("Too many CPUs requested")
        return ret.value

    def bin_os(self, os, snapshot):
        from ._osinfo import HostOS as fHostOS
        ret = None
        if snapshot:
            ret = self.OS.SNAPSHOT
        else:
            if os==fHostOS.FreeBSD_12_0:
                ret = self.OS.FreeBSD_12_0
            else:
                raise Exception("Operating system not supported by API")
        return ret.value

    def __init__(self, apikey):
        self.api = vultr.Vultr(apikey if apikey else getenv().extcreds['vultr']['apikey'])

    def block_create(self, blockstore):
        location = self.bin_location(blockstore.location)
        rets = self.api.block.create(location, blockstore.appmnt.size_gb, blockstore.blockstore_name)
        return {
            'vsubid' : rets['SUBID']
        }

    def block_delete(self, subid):
        rets = self.api.block.delete(subid)
        return

    def block_delete_mark(self, blockstore):
        self.api.block.label_set(blockstore['vsubid'], 'delete:%s' % blockstore['label'])

    def block_list(self, show_delete=False):
        rets = [{
            'vsubid'     : ret['SUBID'],
            'label'      : ret['label'],
            'crdatetime' : ret['date_created'],
            'asset'      : ret
        } for ret in self.api.block.list()]
        filtered = rets if show_delete else [ret for ret in rets if ret['label'][:6]!='delete']
        return sorted(filtered, key=lambda x: x['crdatetime'], reverse=True)

    def server_create(self, host, snapshot=None, label=None):

        snapshot = snapshot['vsubid']
        vpstype  = self.bin_host_plan(host)
        location = self.bin_location(host.site.location)
        osid     = self.bin_os(host.os, snapshot)

        self.api.server.create(location, vpstype, osid, snapshotid=snapshot, label=label)

    def server_delete_mark(self, server):
        self.api.server.label_set(server['vsubid'], 'delete:%s' % server['label'])

    def server_list(self, show_delete=False):
        api_ret = self.api.server.list()
        rets = [{
            'vsubid'     : k,
            'label'      : v['label'],
            'crdatetime' : v['date_created'],
            'asset'      : v,
        } for k, v in ({} if len(api_ret)==0 else api_ret.items())]
        filtered = rets if show_delete else [ret for ret in rets if ret['label'][:6]!='delete']
        return sorted(filtered, key=lambda x: x['crdatetime'], reverse=True)

    def snapshot_list(self):
        api_ret = self.api.snapshot.list()
        rets = [{
            'vsubid'     : k,
            'label'      : v['description'],
            'crdatetime' : v['date_created'],
            'asset'      : v,
        } for k, v in ({} if len(api_ret)==0 else api_ret.items())]
        return sorted(rets, key=lambda x: x['crdatetime'], reverse=True)

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
