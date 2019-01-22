#!/usr/bin/env python3

__all__ = ['Domain', 'Site', 'Host', 'Deployment', 'Netif', 'HostTemplate', 'AppTemplate', 'set_domain', 'HostOS', 'Tunable', 'Provider', 'Location']

import collections
import enum
import ipaddress
import os
import shutil
import tarfile
import toml

from pprint import pprint

from openarc import staticproperty, oagprop
from openarc.dao import OADbTransaction
from openarc.graph import OAG_RootNode
from openarc.exception import OAGraphRetrieveError, OAError
from openarc.env import getenv

from .capabilities import OSCapabilityFactory
from .osinfo import HostOS, Tunable

####### Database structures, be nice

def walk_graph_to_domain(check_node):
    if check_node.__class__ == OAG_Domain:
        return check_node
    else:
        domain_found = None
        for stream in check_node.streams:
            if check_node.is_oagnode(stream):
                payload = getattr(check_node, stream, None)
                if payload:
                    domain_found = walk_graph_to_domain(payload)
                    if domain_found:
                        return domain_found
        return doamin_found

class OAG_FriezeRoot(OAG_RootNode):
    @oagprop
    def root_domain(self, **kwargs):
        return walk_graph_to_domain(self)

def friezetxn(fn):

    # The best thing since sliced bread
    nested_dict = lambda: collections.defaultdict(nested_dict)

    # A simple cloning script
    def db_clone_with_changes(src, repl={}):

        if not src:
            return None

        if clones[src.__class__][src.id]:
            return clones[src.__class__][src.id]

        # recursively descend the subnode graph to
        initprms = {}
        for stream in src.streams:
            payload = getattr(src, stream, None)
            if payload\
                and stream not in repl\
                and src.is_oagnode(stream):
                    if clones[payload.__class__][payload.id]:
                        payload = clones[payload.__class__][payload.id]
                    else:
                        print("cloning subnode %s[%d].%s.id -> [%d]" % (src.__class__, src.id, stream, payload.id))
                        clone = db_clone_with_changes(payload)
                        clones[payload.__class__][payload.id] = clone
                        payload = clone
            initprms[stream] = payload

        initprms = {**initprms, **repl}
        newoag = src.__class__(initprms=initprms, initschema=False).db.create()
        clones[src.__class__][src.id] = newoag

        return newoag

    # Use this to stash previously cloned items
    clones = nested_dict()

    def wrapfn(self, *args, **kwargs):

        if self.root_domain.is_frozen:

            with OADbTransaction("Clone domain") as tran:

                n_domain = db_clone_with_changes(self.root_domain, repl={'version_name' : str()})

                # TODO: this can be inferred recursively from forward keys

                for site in self.root_domain.site:
                    n_site = db_clone_with_changes(site)
                    for host in site.host:
                        n_host = db_clone_with_changes(host)

                        # Clone ifaces recursively
                        for iface in host.net_iface:
                            n_iface = db_clone_with_changes(iface)

                        # Clone tunables
                        for tunable in host.sysctls:
                            n_tunable = db_clone_with_changes(tunable)

                for depl in self.root_domain.deployment:
                    n_depl = db_clone_with_changes(depl)
                    if depl.application:
                        for app in depl.application:
                            n_app = db_clone_with_changes(app)

                for subnet in self.root_domain.subnet:
                    n_subnet = db_clone_with_changes(subnet)

        self.root_domain.db.search()

        return fn(self, *args, **kwargs)
    return wrapfn

class OAG_Domain(OAG_FriezeRoot):
    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def dbindices(cls): return {
        'domain'          : [ ['domain'], False,  None ],
    }

    @staticproperty
    def streams(cls): return {
        'domain'       : [ 'text',    str(),  None ],
        'version_name' : [ 'text',    str(),  None ],
        'deployed'     : [ 'boolean', bool(), None ]
    }

    @friezetxn
    def add_deployment(self, name, affinity=None):
        try:
            depl = OAG_Deployment((self, name), 'by_name')
        except OAGraphRetrieveError:
            depl =\
                OAG_Deployment().db.create({
                    'domain'    : self,
                    'name'      : name
                })

            for site in self.site:
                for host in site.host:
                    host.add_iface('vlan%d' % depl.id, type_=OAG_NetIface.Type.VLAN)

        return depl

    @friezetxn
    def add_site(self, sitename, shortname, provider, location):
        try:
            site = OAG_Site((self, sitename), 'by_name')
        except OAGraphRetrieveError:
            site =\
                OAG_Site().db.create({
                    'domain'    : self,
                    'name'      : sitename,
                    'shortname' : shortname,
                    'provider'  : provider,
                    'location'  : location,
                })

        return site

    @friezetxn
    def assign_subnet(self, type_, iface=None):
        # Save a subnet for administration
        if type_==OAG_Subnet.Type.ROUTING:
            sid = '172.16.0'
        elif type_==OAG_Subnet.Type.SITE:
            site_subnets = self.subnet.rdf.filter(lambda x: OAG_Subnet.Type(x.type)==OAG_Subnet.Type.SITE)

            if site_subnets.size==0:
                sid = '172.16.1'
            else:
                sid = '172.16.%d' % (int(site_subnets[-1].sid.split('.')[-1])+1)
        else:
            depl_subnets = self.subnet.rdf.filter(lambda x: OAG_Subnet.Type(x.type)==OAG_Subnet.Type.DEPLOYMENT)

            if depl_subnets.size==0:
                sid = '10.0.0'
            else:
                sid = '10.0.%d' % (int(depl_subnets[-1].sid.split('.')[-1])+1)

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

    @oagprop
    def containers(self, **kwargs):
        """Global view of jobs. Can be filtered by OAG_Deployment or OAG_Site
        to determine what the distribution of containers"""

        # Create resource map
        resources = {}
        for site in self.site:
            try:
                resources[site.shortname]
            except KeyError:
                resources[site.shortname] = {}

            for i, host in enumerate(site.compute_hosts):
                try:
                    resources[site.shortname][host.fqdn]
                except KeyError:
                    resources[site.shortname][host.fqdn] = host.clone()[i]

        # Containers are placed deployment first, site second. Affinity free
        # definitions are placed wherever there is room. If resources are not
        # available, they are not entered in the app mapping
        containers = [['application', 'site', 'host']]
        unplaceable_apps = []
        for depl in self.deployment:

            if depl.application:
                # Place site specific applications first
                apps_with_affinity = depl.application.clone().rdf.filter(lambda x: x.affinity is not None)
                for app in apps_with_affinity:
                    site_slot_factor = sum([host.slot_factor for hostname, host in resources[app.affinity.shortname].items()])
                    if site_slot_factor<app.slot_factor:
                        unplaceable_apps.append((app.affinity.id, app.fqdn))
                        continue

                    for hostname, host in resources[app.affinity.shortname].items():
                        if host.slot_factor-app.slot_factor>=0:
                            resources[app.affinity.shortname][hostname].slot_factor -= app.slot_factor
                            containers.append([app.clone(), site.clone(), host.clone()])
                            break

                # Distribute affinity-free resources next
                apps_without_affinity = depl.application.clone().rdf.filter(lambda x: x.affinity is None)
                for app in apps_without_affinity:
                    site_loop_break = False

                    domain_slot_factor = 0
                    for site, hostinfo in resources.items():
                        domain_slot_factor += sum([host.slot_factor for hostname, host in hostinfo.items()])
                    if domain_slot_factor<app.slot_factor:
                        unplaceable_apps.append(('no-affinity', app.fqdn))
                        continue

                    for site, hostinfo in resources.items():
                        if site_loop_break:
                            break
                        for hostname, host in hostinfo.items():
                            if host.slot_factor-app.slot_factor>=0:
                                resources[site][hostname].slot_factor -= app.slot_factor
                                containers.append([app.clone(), OAG_Site((self, site), 'by_shortname')[0], host.clone()])
                                site_loop_break = True
                                break

        if len(unplaceable_apps)>0:
            print("Warning: unable to place the following apps:")
            pprint(unplaceable_apps)

        return OAG_Container(initprms=containers)

    def deploy(self, version_name=str()):

        if self.is_frozen:
            for site in self.site:
                site.prepare_infrastructure()
                site.configure(push=False)
        else:
            raise OAError("Can't deploy domain that hasn't been snapshotted")

    @property
    def is_frozen(self):
        return len(self.version_name)>0

    def snapshot(self, version_name):
        if self.version_name:
            raise OAError("This version has already been snapshot with [%s]" % self.version_name)

        self.version_name = version_name
        self.db.update()

        return self

class OAG_Container(OAG_FriezeRoot):
    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def streamable(cls): return False

    @staticproperty
    def streams(cls): return {
        'application' : [ OAG_Application, True,  None ],
        'site'        : [ OAG_Site,        True,  None ],
        'host'        : [ OAG_Host,        True,  None ],
    }

    @property
    def block_storage(self):
        return OAG_SysMount() if self.site.block_storage.size==0 else self.site.block_storage.clone().rdf.filter(lambda x: x.host.fqdn==self.fqdn)

    @property
    def fqdn(self):
        return self.application.fqdn

class Provider(enum.Enum):
    DIGITALOCEAN = 1
    VULTR        = 2
    DC           = 3

class Location(enum.Enum):
    NY           = 1
    LONDON       = 2

class OAG_Site(OAG_FriezeRoot):
    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def dbindices(cls): return {
        'name'      : [ ['domain', 'name'],      True, None ],
        'shortname' : [ ['domain', 'shortname'], True, None ],
    }

    @staticproperty
    def streams(cls): return {
        'domain'    : [ OAG_Domain, True,  None ],
        'name'      : [ 'text',     str(), None ],
        'shortname' : [ 'text',     str(), None ],
        'provider'  : [ Provider,   True,  None ],
        'location'  : [ Location,   True,  None ],
    }

    @friezetxn
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
                    'name' : name,
                    'role' : role.value,
                    'os' : template.os
                })

            # Add network interfaces
            for iface in template.interfaces:
                if iface[1]:
                    host.add_iface(iface[0], is_external=True)
                else:
                    host.add_iface(iface[0])

            # Add tunable parameters
            for sysctl in template.sysctls:
                OAG_Sysctls().db.create({
                    'host' : host,
                    'tunable' : sysctl[0],
                    'boot' : sysctl[1],
                    'value' : sysctl[2],
                })

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
        compute_hosts = self.host.clone().rdf.filter(lambda x: not x.is_bastion)
        if compute_hosts.size>0:
            return compute_hosts
        else:
            return None

    def configure(self, frieze_dir=None, push=True):

        # Decide on directory to output files to
        if not frieze_dir:
            frieze_dir = os.path.expanduser("~/.frieze")

        version_dir = os.path.join(frieze_dir, self.domain.domain, self.domain.version_name)
        version_deploy_dir = os.path.join(version_dir, 'deploy')
        os.makedirs(version_deploy_dir, exist_ok=True)

        # Create configurations for each host. The configurations contain a
        # full suite of config files,
        for host in self.host:
            host_cfg_dir = os.path.join(version_dir, host.fqdn)

            # Fresh start
            try:
                shutil.rmtree(host_cfg_dir)
            except FileNotFoundError:
                pass
            os.makedirs(host_cfg_dir)

            # Generate host config
            host.configure(host_cfg_dir)

            # Create deployable tarballs
            host_tar_file = os.path.join(version_deploy_dir, '%s.tar.gz' % host.fqdn)
            with tarfile.open(host_tar_file, "w:gz") as tar:
                tar.add(host_cfg_dir)

            # Use Ansible to compress and deploy manifest to each host
            if push:
                pass

    @property
    def containers(self):
        return self.domain.clone()[-1].containers.rdf.filter(lambda x: x.site.id==self.id)

    @oagprop
    def block_storage(self, **kwargs):
        """Analyzes containers on site and returns an OAG_BlockStore object
        listing block storage devices that need to be provided in order to run
        the site"""
        store_init = [['container_name', 'appmnt', 'host']]
        for container in self.containers:
            for app in container.application:
                try:
                    if app.app_required_mount:
                        for arm in app.app_required_mount:
                            store_init.append([container.fqdn, arm.clone(), container.host.clone()])
                except AttributeError:
                    # No apps pointed here yet
                    pass

        return OAG_SysMount() if len(store_init)==1 else OAG_SysMount(initprms=store_init)

    def prepare_infrastructure(self):

        from ._provider import ExtCloud

        # Prep the external provider
        extcloud = ExtCloud(self.provider)

        # Collect block storage
        needed_bs   = [bs.blockstore_name for bs in self.block_storage]
        existing_bs = extcloud.block_list()

        # Create list of block stores that need to be deleted, and mark them
        # for deletion
        delete_bs = [ebs for ebs in existing_bs if ebs['label'] not in needed_bs]
        for bs in delete_bs:
            extcloud.block_delete_mark(bs)

        # Similarly create a list of items that need to be created, and issue
        # creation statements to the API
        if self.block_storage.size>0:
            create_bs = self.block_storage.clone().rdf.filter(lambda x: x.blockstore_name not in [v['label'] for v in existing_bs])
            for bs in create_bs:
                extcloud.block_create(bs)

        # Make sure private network is available
        needed_nw = [self.shortname]
        existing_nw = extcloud.network_list()

        if self.size>0:
            create_nw = self.clone().rdf.filter(lambda x: x.shortname not in [v['label'] for v in existing_nw])
            for nw in create_nw:
                extcloud.network_create(nw)

        # Collect servers, again, taking care to making sure to not create ones
        # that are already created.
        needed_srv = [srv.fqdn for srv in self.host]
        existing_srv = extcloud.server_list()

        delete_srv = [esrv for esrv in existing_srv if esrv['label'] not in needed_srv]
        for srv in delete_srv:
            extcloud.server_delete_mark(srv)

        if self.host.size>0:
            create_srv = self.host.clone().rdf.filter(lambda x: x.fqdn not in [v['label'] for v in existing_srv])
            snapshot = extcloud.snapshot_list()[0]
            for srv in create_srv:
                extcloud.server_create(srv, snapshot, label=srv.fqdn)

        # Attach block storage to relevant servers. block_attach() keeps track
        # of detaching and attaching storage as necessary if our new config has
        # resulted in a container moving from one host to another.
        if self.block_storage.size>0:
            for bs in self.block_storage:
                extcloud.block_attach(bs)

        if self.host.size>0:
            networks = extcloud.network_list()
            for host in self.host:
                for i, netif in enumerate(host.net_iface.rdf.filter(lambda x: OAG_NetIface.Type(x.type)==OAG_NetIface.Type.PHYSICAL)):
                    if i==0:
                        continue
                    else:
                        extcloud.network_attach(host, networks[i-1])

class OAG_SysMount(OAG_FriezeRoot):

    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def streamable(cls): return False

    @staticproperty
    def streams(cls): return {
        'container_name' : [ 'text',   True, None ],
        'appmnt'         : [ OAG_AppRequiredMount, True, None ],
        'host'           : [ OAG_Host, True, None ]
    }

    @property
    def blockstore_name(self):
        return "%s:%s:%s" % (self.host.site.shortname, self.container_name, self.appmnt.mount)

    @property
    def dataset(self):
        return "%s/%s" % (self.zpool, self.appmnt.mount)

    @property
    def default_mountdir(self):
        return '/mnt'

    @property
    def mount_pount(self):
        return "%s/%s" % (self.default_mountdir, self.dataset)

    @property
    def zpool(self):
        return "%s%d" % (self.appmnt.app.service, self.appmnt.app.stripe)

class OAG_AppRequiredMount(OAG_FriezeRoot):

    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def streams(cls): return {
        'app'     : [ OAG_Application, True, None ],
        'mount'   : [ 'text',          True, None ],
        'size_gb' : [ 'int',           True, None ],
    }

class OAG_NetIface(OAG_FriezeRoot):
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

    def __get_subnet(self):
        if self.routed_by:
            return self.routed_by.subnet[-1]

        if self.routingstyle==self.RoutingStyle.STATIC:
            try:
                return self.subnet[-1]
            except TypeError:
                pass

        return None

    @property
    def broadcast(self):
        subnet = self.__get_subnet()
        return subnet.broadcast if subnet else None

    @property
    def connected_ifaces(self):
        return {nif.infname:'%s.%d' % (self.subnet[-1].sid, i+2) for i, nif in enumerate(self.net_iface_routed_by)}

    @property
    def dhcpd_enabled(self):
        return self.host.is_bastion and not self.is_external

    @property
    def gateway(self):
        subnet = self.__get_subnet()
        return subnet.gateway if subnet else None

    @property
    def ip4(self):


        ret = None

        if not self.is_external:


            if self.routingstyle==OAG_NetIface.RoutingStyle.STATIC:
                # IP address is whatever subnet is attached to this interface
                subnet = self.__get_subnet()
                ret = subnet.gateway if subnet else None
            else:
                # IP address is determined by alphasort on
                if self.routed_by:
                    ret = self.routed_by.connected_ifaces[self.infname]

        return ret

    @property
    def is_gateway(self):
        return self.gateway is None

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
                    if OAG_NetIface.Type(self.type)==OAG_NetIface.Type.PHYSICAL:
                        return self.RoutingStyle.DHCP
                    else:
                        return self.RoutingStyle.STATIC
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

class OAG_Subnet(OAG_FriezeRoot):
    """Subnets are doled out on a per-domain basis and then assigned to
    assigned to a site."""
    class Type(enum.Enum):
        ROUTING    = 1
        SITE       = 2
        DEPLOYMENT = 3

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

class OAG_Host(OAG_FriezeRoot):

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
        'name'      : [ 'text',   True, None ],
        'role'      : [ 'int',    True, None ],
        'os'        : [ HostOS,   True, None ],
    }

    @friezetxn
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

    @friezetxn
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

            if type_==OAG_NetIface.Type.VLAN:
                # Assign vlan to internal interface
                iface.vlanhost = self.internal_ifaces[0]
                iface.db.update()

                # Assign subnet to interface
                self.site.domain.assign_subnet(OAG_Subnet.Type.DEPLOYMENT, iface=iface)

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
                        self.site.db.search()
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
    def block_storage(self):
        return OAG_SysMount() if self.site.block_storage.size==0 else self.site.block_storage.clone().rdf.filter(lambda x: x.host.fqdn==self.fqdn)

    @property
    def capabilities(self):
        self.__set_capability()
        return self._capabilities[self.fqdn]

    def configure(self, targetdir):
        pass

    @property
    def containers(self):
        return self.site.domain.clone()[-1].containers.rdf.filter(lambda x: x.host.id==self.id)

    @property
    def fqdn(self):
        return '%s.%s.%s' % (self.name, self.site.shortname, self.site.domain.domain)

    @property
    def internal_ifaces(self):
        return self.net_iface.clone().rdf.filter(lambda x: x.is_external is False)

    @property
    def is_bastion(self):
        return OAG_Host.Role(self.role)==OAG_Host.Role.SITEBASTION

    @property
    def routed_subnets(self):
        return self.subnet.clone()

    @property
    def slot_factor(self):
        try:
            if self._slot_factor is None:
                self._slot_factor = self.memory*self.cpus
        except AttributeError:
            self._slot_factor = self.memory*self.cpus
        return self._slot_factor
    @slot_factor.setter
    def slot_factor(self, val):
        self._slot_factor = val

    def __set_capability(self):
        ccap = {}
        try:
            ccap = self._capabilities
            ccap[self.fqdn]
        except (AttributeError, KeyError):
            # _capabilities doesn't exist yet
            ccap[self.fqdn] = OSCapabilityFactory(self).capabilities

        setattr(self, '_capabilities', ccap)

    def __getitem__(self, indexinfo, preserve_cache=False):
        super().__getitem__(indexinfo, preserve_cache)
        self.__set_capability()
        return self

    def __next__(self):
        super().__next__()
        self.__set_capability()
        return self

class OAG_Sysctls(OAG_FriezeRoot):
    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def dbindices(cls): return {
    }

    @staticproperty
    def streams(cls): return {
        'host'      : [ OAG_Host,  True, None ],
        'tunable'   : [ Tunable,   True, None ],
        'value'     : [ 'text',    True, None ],
        # These tunables are only set at boot time
        'boot'      : [ 'boolean', True, None ]
    }

class OAG_Application(OAG_FriezeRoot):
    """An AppContainer is the running unit of work. """

    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def dbindices(cls): return {
        'name' : [ ['deployment', 'service'], False, None ],
    }

    @staticproperty
    def streams(cls): return {
        'deployment' : [ OAG_Deployment, True,  None ],
        'affinity'   : [ OAG_Site,       False, None ],
        'service'    : [ 'text',         str(), None ],
        'stripe'     : [ 'int',          int(), None ],
        'cores'      : [ 'int',          None,  None ],
        'memory'     : [ 'int',          None,  None ]
    }

    @property
    def fqdn(self):
        return "%s%d.%s.%s" % (self.service, self.stripe, self.deployment.name, self.deployment.domain.domain)

    @property
    def slot_factor(self):
        return (self.cores if self.cores else 0.25) * (self.memory if self.memory else 256)

class OAG_Deployment(OAG_FriezeRoot):
    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def dbindices(cls): return {
        'name' : [ ['domain', 'name'], True, None ],
    }

    @staticproperty
    def streams(cls): return {
        'domain'   : [ OAG_Domain, True,  None ],
        'name'     : [ 'text',     True,  None ],
    }

    @friezetxn
    def add_application(self, template, affinity=None, stripes=1):
        """ Where should we put this new application? Loop through all
        hosts in site and see who has slots open. One slot=1 cpu + 1GB RAM.
        If template doesn't specify cores or memory required, just go ahead
        and put it on the first host with ANY space on it"""

        if isinstance(template, AppTemplate):
            try:
                app = OAG_Application((self, template.name), 'by_name')
                stripe_base = app[-1].stripe+1
            except OAGraphRetrieveError:
                stripe_base = 0

            with OADbTransaction("App Add"):
                for stripe in range(stripes):
                    app =\
                        OAG_Application().db.create({
                            'deployment' : self,
                            'service' : template.name,
                            'stripe' : stripe_base+stripe,
                            'affinity' : affinity,
                            'cores' : template.cores,
                            'memory' : template.memory,
                        })

                    for (mount, size_gb) in template.mounts:
                        appmount =\
                            OAG_AppRequiredMount().db.create({
                                'app' : app,
                                'mount' : mount,
                                'size_gb' : size_gb,
                            })
        else:
            raise OAError("AppGroups not yet supported")

        return self

    @property
    def containers(self):
        containers = {}
        if self.application:
            for app in self.application:
                containers[app.fqdn] = app.clone()
        return containers

class HostTemplate(object):
    def __init__(self, cpus=None, memory=None, bandwidth=None, sysctls=None, os=HostOS.FreeBSD_12_0, interfaces=[]):
        self.cpus = cpus
        self.memory = memory
        self.bandwidth = bandwidth
        self.interfaces = interfaces
        self.os = os
        self.sysctls = sysctls

class AppTemplate(object):
    """An application is a composite of its name, resource requirements, mounts,
    network capabilities and internal configurations"""
    def __init__(self, name, cores=None, memory=None, affinity=None, mounts=[], ports=[], config=[]):
        self.name = name
        # Resource expectations.
        self.cores  = cores
        self.memory = memory
        # Mounts to be fed into the application's container
        self.mounts = mounts
        # Ports to be redirected from outside
        self.ports = ports
        # Config files that need to be set in the container
        self.config = config
        # The site in which we would like this app to be run. None for any site.
        self.affinity = affinity

####### Exportable friendly names go here

Host = OAG_Host
Netif = OAG_NetIface
Domain = OAG_Domain
Site = OAG_Site
Deployment = OAG_Deployment

####### User api goes here

p_domain = None

def domain():
    global p_domain
    return p_domain

def set_domain(domain, cfgfile=None):
    global p_domain
    gen_domain = False

    if p_domain:
        if domain==p_domain:
            return p_domain
        else:
            gen_domain = True
    else:
        gen_domain = True

    if gen_domain:
        try:
            p_domain = OAG_Domain(domain, 'by_domain')[-1]
        except OAGraphRetrieveError:
            p_domain =\
                OAG_Domain().db.create({
                    'domain' : domain,
                    'version_name' : str(),
                    'deployed' : False,
                })

            p_domain.assign_subnet(OAG_Subnet.Type.ROUTING)

    # Load configuration
    def get_cfg_file_path():
        if cfgfile is None:

            cfg_name = "frieze"

            try:
                cfg_file_path = "./%s" % cfg_name
                with open(cfg_file_path, 'r'):
                    return cfg_file_path
            except IOError:
                pass

            try:
                cfg_file_path = os.path.expanduser("~/.%s/%s.conf" % (cfg_name, cfg_name))
                with open(cfg_file_path, 'r'):
                    return cfg_file_path
            except IOError:
                pass

            cfg_file_path = "/usr/local/etc/%s.conf" % cfg_name
        else:
            cfg_file_path = cfgfile

        return cfg_file_path

    cfg_file_path = get_cfg_file_path()
    print("Loading FRIEZE config: [%s]" % (cfg_file_path))
    try:
        with open(cfg_file_path) as f:
            appcfg = toml.loads(f.read())
            getenv().merge_app_cfg(appcfg)
    except IOError:
        raise OAError("%s does not exist" % cfg_file_path)

    return p_domain
