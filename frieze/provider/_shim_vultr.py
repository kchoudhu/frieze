#!/usr/bin/env python3

__all__ = ['VultrShim']

import base64
import enum
import vultr
import ipaddress
import time
import os
import gevent

from openarc import oaenv

from ._interface import CloudInterface

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
        from .public import Location as fLocation
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
        if host.cores == 1:
            ret = self.Plan.VPS_1_1_25 if gb_memory < 2 else self.Plan.VPS_1_2_40
        elif host.cores == 2:
            ret = self.Plan.VPS_2_4_60
        elif 2 < host.cores <= 4:
            ret = self.Plan.VPS_4_8_100
        elif 4 < host.cores <= 6:
            ret = self.Plan.VPS_6_16_200
        elif 6 < host.cores <= 8:
            ret = self.Plan.VPS_8_32_300
        elif 8 < host.cores <= 16:
            ret = self.Plan.VPS_16_64_400
        elif 16 < host.cores <=24:
            ret = self.Plan.VPS_24_96_800
        else:
            raise Exception("Too many cores requested")
        return ret.value

    def bin_os(self, os, snapshot):
        from ..osinfo import HostOS as fHostOS
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
        self.api = vultr.Vultr(apikey if apikey else oaenv('frieze').extcreds.vultr.apikey)

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

    def block_rootdisk(self):
        return ('vtbd', 0)

    def metadata_set_user_data(self, userdata):
        """Vultr sucks and doesn't have a userdata field so we smuggle the
        information in on the comment of the ssh key. Yes, the SSH key."""
        for sshkey in self.sshkey_list():
            self.sshkey_destroy(sshkey)

        self.sshkey_create(
            # Use same label
            sshkey['label'],
            # Reset SSH key
            ' '.join(sshkey['asset']['ssh_key'].split(' ')[:2]),
            # Add in user data as additional_data
            additional_data=userdata)

    def network_attach(self, host, network):
        print("Looking up private network status for [%s]" % host.fqdn)
        v_host = [v_host for v_host in self.server_list() if v_host['label']==host.fqdn][0]
        v_pnws = [pnw['vsubid'] for pnw in self.server_private_network_list(v_host['vsubid'])]
        if network['vsubid'] not in v_pnws:
            print("  Network is currently unattached")
            print("  Making call to attach [%s] to [%s]/[%s]" % (network['vsubid'], v_host['vsubid'], v_host['label']))
            self.api.server.private_network_enable(v_host['vsubid'], network['vsubid'])
        else:
            print("  Network [%s] is already attached to [%s]/[%s]" % (network['vsubid'], v_host['vsubid'], v_host['label']))

    def network_create(self, site, label=None):

        location = self.bin_location(site.location)

        self.api.network.create(location, description=site.shortname)

    def network_iface_mtu(self, external=True):
        return None if external else 1450

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

    def server_create(self, host, networks=[], sshkey=None, snapshot=None, label=None):

        network  = ','.join([nw['vsubid'] for nw in networks])
        sshkey   = sshkey['vsubid']
        snapshot = snapshot['vsubid']
        vpstype  = self.bin_host_plan(host)
        location = self.bin_location(host.site.location)
        osid     = self.bin_os(host.os, snapshot)

        v_srv_subid = self.api.server.create(location, vpstype, osid, networkid=network, sshid=sshkey, snapshotid=snapshot, label=label)

        v_srv = self.server_list(v_srv_subid['SUBID'])

        def system_up(ip4):
            # <seanconnery>One ping only</seanconnery>
            return not os.system("ping -c 1 %s >/dev/null 2>&1" % ip4)

        while ipaddress.ip_address(v_srv['ip4']).is_private:
            print("[%s] Creation: waiting for IP address" % host.fqdn)
            gevent.sleep(10)
            v_srv = self.server_list(v_srv_subid['SUBID'])

        while not system_up(v_srv['ip4']):
            print("[%s] Creation: Waiting for network response from [%s]" % (host.fqdn, v_srv['ip4']))
            gevent.sleep(10)

        print("[%s] Creation: Done" % host.fqdn)

        return v_srv

    def server_delete_mark(self, server):
        self.api.server.label_set(server['vsubid'], 'delete:%s' % server['label'])

    def server_list(self, subid=None, show_delete=False):
        api_ret = self.api.server.list(subid)
        if subid:
            return {
                'vsubid'     : api_ret['SUBID'],
                'label'      : api_ret['label'],
                'crdatetime' : api_ret['date_created'],
                'ip4'        : api_ret['main_ip'],
                'gateway4'   : api_ret['gateway_v4'],
                'netmask4'   : api_ret['netmask_v4'],
                'asset'      : api_ret
            }
        else:
            rets = [{
                'vsubid'     : k,
                'label'      : v['label'],
                'crdatetime' : v['date_created'],
                'ip4'        : v['main_ip'],
                'gateway4'   : v['gateway_v4'],
                'netmask4'   : v['netmask_v4'],
                'asset'      : v,
            } for k, v in ({} if len(api_ret)==0 else api_ret.items())]
            filtered = rets if show_delete else [ret for ret in rets if ret['label'][:6]!='delete']
            return sorted(filtered, key=lambda x: x['crdatetime'], reverse=True)

    def server_private_network_list(self, subid):
        api_ret = self.api.server.private_network_list(subid)
        return [{
            'vsubid'     : k,
            'mac'        : v['mac_address'],
            'asset'      : v,
        } for k, v in ({} if len(api_ret)==0 else api_ret.items())]

    def sshkey_create(self, name, pubkey, additional_data=None):
        if additional_data:
            pubkey += ' %s' % base64.b64encode(additional_data.encode()).decode()
        self.api.sshkey.create(name, pubkey)

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
