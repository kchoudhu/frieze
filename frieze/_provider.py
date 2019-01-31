#!/usr/bin/env python3

__all__ = ['ExtCloud']

import enum
import vultr

from openarc.env import getenv

class CloudInterface(object):
    """Minimal functionality that needs to be implemented by a deriving shim
    to a cloud service"""
    def block_attach(self, blockstore):
        raise NotImplementedError("Implement in deriving Shim")

    def block_create(self, blockstore):
        raise NotImplementedError("Implement in deriving Shim")

    def block_detatch(self, blockstore):
        raise NotImplementedError("Implement in deriving Shim")

    def block_delete(self, subid):
        raise NotImplementedError("Implement in deriving Shim")

    def block_delete_mark(self, subid, label):
        raise NotImplementedError("Implement in deriving Shim")

    def block_list(self, show_delete=False):
        raise NotImplementedError("Implement in deriving Shim")

    def network_attach(self, host, network):
        raise NotImplementedError("Implement in deriving Shim")

    def network_create(self, site, label=None):
        raise NotImplementedError("Implement in deriving Shim")

    def network_list(self, show_delete=False):
        raise NotImplementedError("Implement in deriving Shim")

    def server_create(self, host, snapshot=None, label=None):
        raise NotImplementedError("Implement in deriving Shim")

    def server_delete_mark(self, server):
        raise NotImplementedError("Implement in deriving Shim")

    def server_list(self, show_delete=False):
        raise NotImplementedError("Implement in deriving Shim")

    def server_private_network_list(self):
        raise NotImplementedError("Implement in deriving Shim")

    def snapshot_list(self):
        raise NotImplementedError("Implement in deriving Shim")

    def sshkey_create(self, certauthority):
        raise NotImplementedError("Implement in deriving Shim")

    def sshkey_destroy(self, keyid):
        raise NotImplementedError("Implement in deriving Shim")

    def sshkey_list(self):
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
        from .osinfo import HostOS as fHostOS
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

    def block_attach(self, blockstore):
        v_blockstores = self.block_list()

        print("Looking up mount status of %s" % blockstore.blockstore_name)
        v_bs = [v_bs for v_bs in v_blockstores if v_bs['label']==blockstore.blockstore_name][0]
        v_curr_mounthost_subid = v_bs['asset']['attached_to_SUBID']

        v_hosts = self.server_list()
        v_req_mounthost = [v_host for v_host in v_hosts if v_host['label']==blockstore.host.fqdn][0]

        if v_curr_mounthost_subid is None:
            print("  Blockstore is currently unmounted")
            print("  Making call to attach [%s] to [%s]/[%s]" % (v_bs['vsubid'], v_req_mounthost['vsubid'], v_req_mounthost['label']))
            api_ret = self.api.block.attach(v_bs['vsubid'], v_req_mounthost['vsubid'])
        else:
            v_curr_mounthost = [v_host for v_host in v_hosts if v_host['vsubid']==str(v_curr_mounthost_subid)][0]
            print("  [%s] currently mounted on: [%s]/[%s]" % (v_bs['vsubid'], v_curr_mounthost['vsubid'], v_curr_mounthost['label']))
            if v_curr_mounthost['label'] != blockstore.host.fqdn:
                print("  Making call to detach [%s] from incorrect host" % v_bs['vsubid'])
                api_ret = self.api.block.detach(v_bs['vsubid'])
                print("  Making call to attach [%s] to [%s]/[%s]" % (v_bs['vsubid'], v_req_mounthost['vsubid'], v_req_mounthost['label']))
                api_ret = self.api.block.attach(v_bs['vsubid'], v_req_mounthost['vsubid'])
            else:
                print("  [%s] already mounted on correct host [%s]/[%s]" % (v_bs['vsubid'], v_req_mounthost['vsubid'], v_req_mounthost['label']))

    def block_create(self, blockstore):
        location = self.bin_location(blockstore.host.site.location)
        rets = self.api.block.create(location, blockstore.capmnt.size_gb, blockstore.blockstore_name)
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

    def network_attach(self, host, network):
        print("Looking up private network status for [%s]" % host.fqdn)
        v_host = [v_host for v_host in self.server_list() if v_host['label']==host.fqdn][0]
        v_pnws = self.server_private_network_list(v_host['vsubid'])
        if network['vsubid'] not in v_pnws:
            print("  Network is currently unattached")
            print("  Making call to attach [%s] to [%s]/[%s]" % (network['vsubid'], v_host['vsubid'], v_host['label']))
            self.api.server.private_network_enable(v_host['vsubid'], network['vsubid'])
        else:
            print("  Network [%s] is already attached to [%s]/[%s]" % (network['vsubid'], v_host['vsubid'], v_host['label']))

    def network_create(self, site, label=None):

        location = self.bin_location(site.location)

        self.api.network.create(location, description=site.shortname)

    def network_list(self, show_delete=False):
        api_ret = self.api.network.list()
        rets = [{
            'vsubid'     : k,
            'label'      : v['description'],
            'crdatetime' : v['date_created'],
            'asset'      : v,
        } for k, v in ({} if len(api_ret)==0 else api_ret.items())]
        filtered = rets if show_delete else [ret for ret in rets if ret['label'][:6]!='delete']
        return sorted(filtered, key=lambda x: x['crdatetime'], reverse=True)

    def server_create(self, host, sshkey=None, snapshot=None, label=None):

        sshkey   = sshkey['vsubid']
        snapshot = snapshot['vsubid']
        vpstype  = self.bin_host_plan(host)
        location = self.bin_location(host.site.location)
        osid     = self.bin_os(host.os, snapshot)

        self.api.server.create(location, vpstype, osid, sshid=sshkey, snapshotid=snapshot, label=label)

    def server_delete_mark(self, server):
        self.api.server.label_set(server['vsubid'], 'delete:%s' % server['label'])

    def server_list(self, subid=None, show_delete=False):
        api_ret = self.api.server.list(subid)
        rets = [{
            'vsubid'     : k,
            'label'      : v['label'],
            'crdatetime' : v['date_created'],
            'asset'      : v,
        } for k, v in ({} if len(api_ret)==0 else api_ret.items())]
        filtered = rets if show_delete else [ret for ret in rets if ret['label'][:6]!='delete']
        return sorted(filtered, key=lambda x: x['crdatetime'], reverse=True)

    def server_private_network_list(self, subid):
        api_ret = self.api.server.private_network_list(subid)
        return [ k for k, v in ({} if len(api_ret)==0 else api_ret.items())]

    def sshkey_create(self, certauthority):
        from .auth import CertFormat
        self.api.sshkey.create(certauthority.name, certauthority.certificate(certformat=CertFormat.SSH))

    def sshkey_destroy(self, key):
        self.api.sshkey.destroy(key['vsubid'])

    def sshkey_list(self):
        api_ret = self.api.sshkey.list()
        rets = [{
            'vsubid'     : k,
            'label'      : v['name'],
            'crdatetime' : v['date_created'],
            'asset'      : v,
        } for k, v in ({} if len(api_ret)==0 else api_ret.items())]
        return sorted(rets, key=lambda x: x['crdatetime'], reverse=True)

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
