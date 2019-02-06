#!/usr/bin/env python3

__all__ = ['Domain', 'Site', 'Host', 'Deployment', 'Netif', 'HostTemplate', 'set_domain', 'HostOS', 'Tunable', 'TunableType', 'Provider', 'Location']

import base64
import collections
import enum
import gevent
import io
import openarc.env
import os
import pkg_resources as pkg
import pwd
import shutil
import tarfile
import toml

from pprint import pprint

from openarc import staticproperty, oagprop
from openarc.dao import OADbTransaction
from openarc.graph import OAG_RootNode
from openarc.exception import OAGraphRetrieveError, OAError

from .auth import CertAuth, CertFormat
from .osinfo import HostOS, Tunable, TunableType, OSFamily
from .capability import ConfigGenFreeBSD, ConfigGenLinux, CapabilityTemplate

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
    @staticproperty
    def streamable(self): return False

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

                        # Clone interfaces recursively
                        for iface in host.net_iface:
                            n_iface = db_clone_with_changes(iface)

                        # Clone tunables
                        for tunable in host.sysctl:
                            n_tunable = db_clone_with_changes(tunable)

                for depl in self.root_domain.deployment:
                    n_depl = db_clone_with_changes(depl)
                    if depl.capability:
                        for cap in depl.capability:
                            n_cap = db_clone_with_changes(cap)

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
    def streamable(self): return True

    @staticproperty
    def streams(cls): return {
        'domain'       : [ 'text',    str(),  None ],
        'country'      : [ 'text',    str(),  None ],
        'province'     : [ 'text',    str(),  None ],
        'locality'     : [ 'text',    str(),  None ],
        'org'          : [ 'text',    str(),  None ],
        'org_unit'     : [ 'text',    str(),  None ],
        'contact'      : [ 'text',    str(),  None ],
        'version_name' : [ 'text',    str(),  None ],
        'deployed'     : [ 'boolean', bool(), None ],
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

    def assign_certificate_authority(self):
        if not self.certauthority.is_valid:
            self.certauthority.generate()
        else:
            print("Not refreshing certificate authority")

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
    def certauthority(self, **kwargs):
        return CertAuth(self)

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
        # available, they are not entered in the capability mapping
        containers = [['capability', 'site', 'host']]
        unplaceable_caps = []
        for depl in self.deployment:

            if depl.capability:
                # Place site specific capabilities first
                caps_with_affinity = depl.capability.clone().rdf.filter(lambda x: x.affinity is not None)
                for cap in caps_with_affinity:
                    site_slot_factor = sum([host.slot_factor for hostname, host in resources[cap.affinity.shortname].items()])
                    if site_slot_factor<cap.slot_factor:
                        unplaceable_caps.append((cap.affinity.id, cap.fqdn))
                        continue

                    for hostname, host in resources[cap.affinity.shortname].items():
                        if host.slot_factor-cap.slot_factor>=0:
                            resources[cap.affinity.shortname][hostname].slot_factor -= cap.slot_factor
                            containers.append([cap.clone(), site.clone(), host.clone()])
                            break

                # Distribute affinity-free resources next
                caps_without_affinity = depl.capability.clone().rdf.filter(lambda x: x.affinity is None)
                for cap in caps_without_affinity:
                    site_loop_break = False

                    domain_slot_factor = 0
                    for site, hostinfo in resources.items():
                        domain_slot_factor += sum([host.slot_factor for hostname, host in hostinfo.items()])
                    if domain_slot_factor<cap.slot_factor:
                        unplaceable_caps.append(('no-affinity', cap.fqdn))
                        continue

                    for site, hostinfo in resources.items():
                        if site_loop_break:
                            break
                        for hostname, host in hostinfo.items():
                            if host.slot_factor-cap.slot_factor>=0:
                                resources[site][hostname].slot_factor -= cap.slot_factor
                                containers.append([cap.clone(), OAG_Site((self, site), 'by_shortname')[0], host.clone()])
                                site_loop_break = True
                                break

        if len(unplaceable_caps)>0:
            print("Warning: unable to place the following caps:")
            pprint(unplaceable_caps)

        return OAG_Container(initprms=containers)

    def deploy(self, version_name=str()):

        if self.is_frozen:
            # Distribute the cert authority first so that we can link
            # them to the servers that are going to be set up shortly
            self.certauthority.distribute()

            for site in self.site:
                site.prepare_infrastructure()
                site.configure(push=True)
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
        'capability'  : [ OAG_Capability, True,  None ],
        'site'        : [ OAG_Site,        True,  None ],
        'host'        : [ OAG_Host,        True,  None ],
    }

    @property
    def block_storage(self):
        return OAG_SysMount() if self.site.block_storage.size==0 else self.site.block_storage.clone().rdf.filter(lambda x: x.host.fqdn==self.fqdn)

    @property
    def fqdn(self):
        return self.capability.fqdn

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
    def streamable(self): return True

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
                if sysctl[0].family == host.os.family:
                    OAG_Sysctl().db.create({
                        'host' : host,
                        'tunable' : sysctl[0],
                        'type' : sysctl[1],
                        'value' : sysctl[2],
                    })
                else:
                    print("[%s] tunable not compatible with [%s]" % (sysctl[0], host.os))

            # On host (i.e. bare metal, non-jailed processes)
            for cap in template.caps:
                host.add_capability(cap[0], default_state=cap[1])

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

    def configure(self, push=True):

        # Decide on directory to output files to
        version_dir = os.path.join(openarc.env.getenv().runprops['home'], 'domains', self.domain.domain, 'deploy', self.domain.version_name)

        # Fresh start: version deployment directory
        version_deploy_dir = os.path.join(version_dir, 'dist')
        try:
            shutil.rmtree(version_deploy_dir)
        except FileNotFoundError:
            pass
        os.makedirs(version_deploy_dir, exist_ok=True)

        # Create new SSH credentials for this deployment if we are pushing
        if push:
            user = pwd.getpwuid(os.getuid())[0]
            command = 'Deploy {%s:%s}' % (self.domain.domain, self.domain.version_name)
            self.domain.certauthority.issue_ssh_certificate(user, command, serialize_to_dir=os.path.join(version_dir, '.ssh'))

        # Create configurations for each host. The configurations contain a
        # full suite of config files,
        for host in self.host:

            # Fresh start: host config directory
            host_cfg_dir = os.path.join(version_dir, host.fqdn)
            try:
                shutil.rmtree(host_cfg_dir)
            except FileNotFoundError:
                pass
            os.makedirs(host_cfg_dir)

            # Generate host config
            host.configure(host_cfg_dir)

            # Create deployable archives
            host_tar_file = os.path.join(version_deploy_dir, '%s.tar.bz2' % host.fqdn)
            with tarfile.open(host_tar_file, "w:bz2") as tar:
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
        store_init = [['container_name', 'capmnt', 'host']]
        for container in self.containers:
            for cap in container.capability:
                try:
                    if cap.cap_required_mount:
                        for crm in cap.cap_required_mount:
                            store_init.append([container.fqdn, crm.clone(), container.host.clone()])
                except AttributeError:
                    # No caps pointed here yet
                    pass

        return OAG_SysMount() if len(store_init)==1 else OAG_SysMount(initprms=store_init)

    def prepare_infrastructure(self):

        from ._provider import ExtCloud

        # Prep the external provider
        extcloud = ExtCloud(self.provider)

        # Create your server configinit tarball
        #
        # Each configinit command goes in its own archive member ("tarinfo"),
        # which is then added to the archive ("tarout"), which is then converted
        # to base64 for decoding by openssl on the server.
        tarout = io.BytesIO()
        cfi_raw = pkg.resource_string('frieze.resources.firstboot', 'configinit.payload').decode()
        cfi_items = ['#!\n'+i[2:] for i in cfi_raw.split('\n') if len(i)>0]
        with tarfile.open(fileobj=tarout, mode="w") as tar:
            for i, cfi in enumerate(cfi_items):
                tarinfo = tarfile.TarInfo(name='{:0>4}.cfg'.format(i))

                payload = io.BytesIO()
                tarinfo.size = payload.write(cfi.encode())
                payload.seek(0)

                tar.addfile(tarinfo=tarinfo, fileobj=payload)
            cfi_push = tarout.getvalue().decode()
        extcloud.metadata_set_user_data(cfi_push)

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

        # List all servers that already exist in cloud
        existing_csrv = extcloud.server_list()

        # ... of which some should be deleted:
        delete_srv = [esrv for esrv in existing_csrv if esrv['label'] not in [srv.fqdn for srv in self.host]]
        for srv in delete_srv:
            extcloud.server_delete_mark(srv)

        # ... and some should be created:
        if self.host.size>0:

            # Update local IP information for servers that already exist in cloud.
            leave_srv  = self.host.clone().rdf.filter(lambda x: x.fqdn in [v['label'] for v in existing_csrv])
            for srv in leave_srv:
                c_srv = [v for v in existing_csrv if v['label']==srv.fqdn][0]
                srv.db.update({
                    'ip4'     : c_srv['ip4'],
                    'gateway' : c_srv['gateway4'],
                    'netmask' : c_srv['netmask4']
                })

            # Create new servers based on what isn't already present on cloud provider. Spawn
            # greenlets to get the job done faster. extcloud.server_create is guaranteed to
            # wait until network activity is detected from newly created server.
            create_srv = self.host.clone().rdf.filter(lambda x: x.fqdn not in [v['label'] for v in existing_csrv])

            networks = extcloud.network_list()
            snapshot = extcloud.snapshot_list()[0]
            sshkey = extcloud.sshkey_list()[0]

            def blocking_server_create(srv):
                c_srv = extcloud.server_create(srv, networks=networks, sshkey=sshkey, snapshot=snapshot, label=srv.fqdn)
                srv.db.update({
                    'ip4'     : c_srv['ip4'],
                    'gateway' : c_srv['gateway4'],
                    'netmask' : c_srv['netmask4']
                })
                return True

            glets = []
            for i, srv in enumerate(create_srv):
                glets.append(gevent.spawn(blocking_server_create, srv.clone()[i]))
            gevent.joinall(glets)

            # Update MAC information on network interfaces based on refreshed external cloud list.
            existing_csrv = extcloud.server_list()
            for host in self.host:

                c_srv = [c_srv for c_srv in existing_csrv if c_srv['label']==host.fqdn][0]
                c_srv_networks = extcloud.server_private_network_list(c_srv['vsubid'])

                for i, iface in enumerate(host.physical_ifaces):
                    if i>0:
                        iface.db.update({
                            'mac' : c_srv_networks[i-1]['mac']
                        })

        # Attach block storage to relevant servers. block_attach() keeps track
        # of detaching and attaching storage as necessary if our new config has
        # resulted in a container moving from one host to another.
        if self.block_storage.size>0:
            for bs in self.block_storage:
                extcloud.block_attach(bs)

class OAG_SysMount(OAG_FriezeRoot):

    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def streamable(cls): return False

    @staticproperty
    def streams(cls): return {
        'container_name' : [ 'text',   True, None ],
        'capmnt'         : [ OAG_CapRequiredMount, True, None ],
        'host'           : [ OAG_Host, True, None ]
    }

    @property
    def blockstore_name(self):
        return "%s:%s:%s" % (self.host.site.shortname, self.container_name, self.capmnt.mount)

    @property
    def dataset(self):
        return "%s/%s" % (self.zpool, self.capmnt.mount)

    @property
    def default_mountdir(self):
        return '/mnt'

    @property
    def mount_pount(self):
        return "%s/%s" % (self.default_mountdir, self.dataset)

    @property
    def zpool(self):
        return "%s%d" % (self.capmnt.cap.service, self.capmnt.cap.stripe)

class OAG_CapRequiredMount(OAG_FriezeRoot):

    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def streamable(self): return True

    @staticproperty
    def streams(cls): return {
        'cap'     : [ OAG_Capability, True, None ],
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
    def streamable(self): return True

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
        # Interface is a VLAN cloned off a parent interface
        'vlanhost'    : [ OAG_NetIface, False, None ],
        # Interface which routes traffic from this interface
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
        if self.is_external:
            return self.host.netmask
        else:
            subnet = self.__get_subnet()
            return subnet.broadcast if subnet else None

    @property
    def connected_ifaces(self):
        """Generate IP addressing map on the fly for a given routing interface.

        Return the map keyed by inferred name for easy lookup by other interfaces
        trying to learn their IP address. See @property ip4 for example on use."""
        return {nif.infname:'%s.%d' % (self.subnet[-1].sid, i+2) for i, nif in enumerate(self.net_iface_routed_by)}

    @property
    def dhcpd_enabled(self):
        return self.host.is_bastion and not self.is_external

    @property
    def gateway(self):
        if self.is_external:
            return self.host.gateway
        else:
            subnet = self.__get_subnet()
            return subnet.gateway if subnet else None

    @property
    def ip4(self):

        ret = None

        if self.is_external:
            ret = self.host.ip4
        else:
            if not self.is_external:
                if self.routingstyle==OAG_NetIface.RoutingStyle.STATIC:
                    # This is an interface responsible for assigning IP addresses
                    # to other interfaces on the subnet so its IP address is that
                    # of the subnet it is routing.
                    subnet = self.__get_subnet()
                    ret = subnet.gateway if subnet else None
                else:
                    # Only assign IP address to routers that are being routed by
                    # another interface.
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

    def summarize(self):
        """Purely informational, shouldn't appear anywhere in production code!"""
        formatstr = "    %-10s|%-20s|%-10s|%-10s|%-10s|%-15s|%-15s|%-15s"
        print(formatstr % (
            self.name,
            self.routingstyle,
            self.bird_enabled,
            self.dhcpd_enabled,
            self.is_gateway,
            self.ip4,
            self.gateway,
            self.broadcast))

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
    def streamable(self): return True

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
    def streamable(self): return True

    @staticproperty
    def streams(cls): return {
        'site'      : [ OAG_Site, True, None ],
        'cpus'      : [ 'int',    True, None ],
        'memory'    : [ 'int',    True, None ],
        'bandwidth' : [ 'int',    True, None ],
        'name'      : [ 'text',   True, None ],
        'role'      : [ 'int',    True, None ],
        'os'        : [ HostOS,   True, None ],
        'ip4'       : [ 'text',   None, None ],
        'gateway'   : [ 'text',   None, None ],
        'netmask'   : [ 'text',   None, None ],
    }

    @friezetxn
    def add_capability(self, template, default_state=True):
        """Run an capability on a host. Enable it."""
        if isinstance(template(), CapabilityTemplate):
            create = True
            try:
                cap = OAG_Capability((self, template.name), 'by_host_capname')
                print("Only single stripes supported for baremetal processes, not enabling [%s]" % template.name)
                create = False
            except OAGraphRetrieveError:
                pass

            with OADbTransaction("App Add"):
                if create:
                    cap =\
                        OAG_Capability().db.create({
                            'deployment' : None,
                            'host' : self,
                            'service' : template.name,
                            'stripe' : 0,
                            'affinity' : None,
                            'cores' : template.cores if template.cores else 0,
                            'memory' : template.memory if template.memory else 0,
                            'enabled' : default_state,
                        })

                    if template.mounts:
                        raise OAError("Mounts not supported for baremetal caps")
        else:
            raise OAError("AppGroups not yet supported")

        return self

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
                # Assign VLAN to internal interface
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
                        # internal interfaces on compute hosts in sites with a bastion:
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
                        # There is no internal routing for this setup yet
                        pass

        return iface

    @property
    def block_storage(self):
        return OAG_SysMount() if self.site.block_storage.size==0 else self.site.block_storage.clone().rdf.filter(lambda x: x.host.fqdn==self.fqdn)

    @property
    def configprovider(self):
        return {
            OSFamily.FreeBSD : ConfigGenFreeBSD,
            OSFamily.Linux : ConfigGenLinux
        }[self.os.family](self)

    def configure(self, targetdir):
        self.configprovider.generate().emit_output(targetdir)

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
    def physical_ifaces(self):
        return self.net_iface.clone().rdf.filter(lambda x: OAG_NetIface.Type(x.type)==OAG_NetIface.Type.PHYSICAL)

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

class OAG_Sysctl(OAG_FriezeRoot):
    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def dbindices(cls): return {
    }

    @staticproperty
    def streamable(self): return True

    @staticproperty
    def streams(cls): return {
        'host'      : [ OAG_Host,    True, None ],
        'tunable'   : [ Tunable,     True, None ],
        'value'     : [ 'text',      True, None ],
        # These tunables are only set at boot time
        'type'      : [ TunableType, True, None ]
    }

class OAG_Capability(OAG_FriezeRoot):
    """An AppContainer is the running unit of work. """

    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def dbindices(cls): return {
        'host_capname' : [ ['host',       'service'], False, None ],
        'depl_capname' : [ ['deployment', 'service'], False, None ],
    }

    @staticproperty
    def streamable(self): return True

    @staticproperty
    def streams(cls): return {
        'deployment' : [ OAG_Deployment, False, None ],
        'affinity'   : [ OAG_Site,       False, None ],
        'host'       : [ OAG_Host,       False, None ],
        'service'    : [ 'text',         str(), None ],
        'stripe'     : [ 'int',          int(), None ],
        'cores'      : [ 'float',        int(), None ],
        'memory'     : [ 'int',          int(), None ],
        'enabled'    : [ 'bool',         None,  None ],
    }

    def configure(self):
        return ConfigFactory(self).cfg.generate()

    def delete(self):
        self.enabled = None
        self.db.update()

    def disable(self):
        self.enabled=False
        self.db.update()

    def enable(self):
        self.enabled = True
        self.db.update()

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
    def streamable(self): return True

    @staticproperty
    def streams(cls): return {
        'domain'   : [ OAG_Domain, True,  None ],
        'name'     : [ 'text',     True,  None ],
    }

    @friezetxn
    def add_capability(self, template, default_state=True, affinity=None, stripes=1):
        """ Where should we put this new capability? Loop through all
        hosts in site and see who has slots open. One slot=1 cpu + 1GB RAM.
        If template doesn't specify cores or memory required, just go ahead
        and put it on the first host with ANY space on it.

        Also check to make sure that the capability can be containerized,
        and throw if it cannot"""
        if isinstance(template(), CapabilityTemplate):

            if not template.jailable:
                raise OAError("Application [%s] is not jailable and cannot be added to deployment")

            try:
                cap = OAG_Capability((self, template.name), 'by_depl_capname')
                stripe_base = cap[-1].stripe+1
            except OAGraphRetrieveError:
                stripe_base = 0

            with OADbTransaction("App Add"):
                for stripe in range(stripes):
                    cap =\
                        OAG_Capability().db.create({
                            'deployment' : self,
                            'host' : None,
                            'service' : template.name,
                            'stripe' : stripe_base+stripe,
                            'affinity' : affinity,
                            'cores' : template.cores if template.cores else 0,
                            'memory' : template.memory if template.memory else 0,
                            'enabled' : default_state,
                        })

                    for (mount, size_gb) in template.mounts:
                        capmount =\
                            OAG_CapRequiredMount().db.create({
                                'cap' : cap,
                                'mount' : mount,
                                'size_gb' : size_gb,
                            })
        else:
            raise OAError("AppGroups not yet supported")

        return self

    @property
    def containers(self):
        containers = {}
        if self.capability:
            for cap in self.capability:
                containers[cap.fqdn] = cap.clone()
        return containers

class HostTemplate(object):
    def __init__(self, cpus=None, memory=None, bandwidth=None, sysctls=None, os=HostOS.FreeBSD_12_0, interfaces=[], caps=[]):
        self.cpus = cpus
        self.memory = memory
        self.bandwidth = bandwidth
        self.interfaces = interfaces
        self.os = os
        self.sysctls = sysctls
        self.caps = caps

####### Exportable friendly names go here

Host = OAG_Host
Netif = OAG_NetIface
Domain = OAG_Domain
Site = OAG_Site
Deployment = OAG_Deployment

####### User API goes here

p_domain = None

def set_domain(domain,
               org,
               country=None,
               province=None,
               locality=None,
               org_unit=None,
               contact_email=None,
               cfgfile=None):

    ##### Prepare operating environment

    ### Does the operating directory exist?
    operating_directory = os.path.expanduser('~/.frieze')
    if not os.path.exists(operating_directory):
        os.makedirs(operating_directory, mode=0o700)
    os.chmod(operating_directory, 0o700)

    ### Set up the database
    db_directory = os.path.join(operating_directory, 'db')
    if not os.path.exists(db_directory):
        os.makedirs(db_directory, mode=0o700)
    os.chmod(db_directory, 0o700)
    # TODO: Boot a special frieze database here
    # Mount dedicated ZFS dataset at ${FRIEZE}/database
    # Start pg database instance from ${FRIEZE}/database
    # Configure openarc to use this db instance

    ### Set up config directory
    cfg_directory = os.path.join(operating_directory, 'cfg')
    if not os.path.exists(cfg_directory):
        os.makedirs(cfg_directory, mode=0o700)
    os.chmod(cfg_directory, 0o700)

    ### Force openarc to use specified config
    openarc.env.initenv(cfgfile=os.path.join(cfg_directory, 'openarc.toml'), reset=True)

    cfg_file_path = os.path.join(cfg_directory, 'frieze.conf')
    print("Loading FRIEZE config: [%s]" % (cfg_file_path))
    try:
        with open(cfg_file_path) as f:
            appcfg = toml.loads(f.read())
            appcfg['runprops'] = { 'home' : operating_directory }
            openarc.env.getenv().merge_app_cfg(appcfg)

    except IOError:
        raise OAError("%s does not exist" % cfg_file_path)

    # Initialize the domain
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

            # Create first entry for the domain
            with OADbTransaction('Create domain: %s' % domain):
                p_domain =\
                    OAG_Domain().db.create({
                        'domain'       : domain,
                        'country'      : country if country else openarc.env.getenv().rootca['country'],
                        'province'     : province if province else openarc.env.getenv().rootca['province'],
                        'locality'     : locality if locality else openarc.env.getenv().rootca['locality'],
                        'org'          : org,
                        'org_unit'     : org_unit if org_unit else openarc.env.getenv().rootca['organization_unit'],
                        'contact'      : contact_email if contact_email else '%s@%s' % (openarc.env.getenv().rootca['contact_email'], domain),
                        'version_name' : str(),
                        'deployed'     : False,
                    })

                # Assign a subnet
                p_domain.assign_subnet(OAG_Subnet.Type.ROUTING)

                # Generate a certificate authority
                p_domain.assign_certificate_authority()

    return p_domain
