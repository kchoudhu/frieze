__all__ = [
    'Domain',
    'Site',
    'Host',
    'HostRole', 'HostOS',
    'Tunable', 'TunableType',
    'Location',
    'FIB', 'Netif', 'NetifType', 'SubnetType',
    'Deployment',
    'Container',
    'set_domain'
]

import base64
import collections
import enum
import frieze.capability
import gevent
import hashlib
import io
import ipaddress
import openarc.env
import os
import pkg_resources as pkg
import pwd
import shutil
import subprocess
import sys
import tarfile
import tempfile
import toml

from pprint import pprint

from openarc import staticproperty, oagprop
from openarc.dao import OADbTransaction
from openarc.graph import OAG_RootNode
from openarc.exception import OAGraphRetrieveError, OAError

from frieze.osinfo import HostOS, Tunable, TunableType, OSFamily
from frieze.provider import CloudProvider, ExtCloud, Location
from frieze.capability import\
    ConfigGenFreeBSD, ConfigInit, CapabilityTemplate,\
    dhclient as dhc, bird, dhcpd, firstboot, gateway, jail,\
    named, pf, pflog, pflate, resolvconf, zfs
from frieze.capability.server import\
    TrustType, CertAction, CertAuthInternal, CertAuthLetsEncrypt, ExtDNS

#### Some enums
class FIB(enum.Enum):
    DEFAULT     = 0
    WORLD       = 1

class HostRole(enum.Enum):
    SITEROUTER   = 1
    SITEBASTION  = 2
    COMPUTE      = 3
    STORAGE      = 4

class NetifType(enum.Enum):
    PHYSICAL    = 1
    OVPN_SERVER = 2
    OVPN_CLIENT = 3
    VLAN        = 4
    BRIDGE      = 5

class RoutingStyle(enum.Enum):
    DHCP        = 1
    STATIC      = 2
    UNROUTED    = 3

class SubnetType(enum.Enum):
    ROUTING     = 1
    SITE        = 2
    DEPLOYMENT  = 3

#### Database structures

# The best thing since sliced bread
nested_dict = lambda: collections.defaultdict(nested_dict)

# Use this to store cloned oags
p_clone_buffer = None

#### Decorator
def friezetxn(fn):
    def wrapfn(self, *args, **kwargs):
        if self.root_domain.is_frozen:
            raise OAError("This domain is currently frozen. Consider cloning and re-issuing your request")
        else:
            return fn(self, *args, **kwargs)
    return wrapfn

class OAG_FriezeRoot(OAG_RootNode):
    @staticproperty
    def streamable(self): return False

    def walk_graph_to_domain(self, check_node):
        if check_node.__class__ == OAG_Domain:
            return check_node
        else:
            domain_found = None
            for stream in check_node.streams:
                if check_node.is_oagnode(stream):
                    payload = getattr(check_node, stream, None)
                    if payload:
                        domain_found = self.walk_graph_to_domain(payload)
                        if domain_found:
                            return domain_found
            return domain_found

    @oagprop
    def root_domain(self, **kwargs):
        return self.walk_graph_to_domain(self)[-1]

    def db_clone_with_changes(self, src, repl={}):

        global p_clone_buffer

        if p_clone_buffer[src.__class__][src.id]:
            return p_clone_buffer[src.__class__][src.id]

        # recursively descend the subnode graph to
        initprms = {}
        for stream in src.streams:
            payload = getattr(src, stream, None)
            if payload\
                and stream not in repl\
                and src.is_oagnode(stream):
                    if p_clone_buffer[payload.__class__][payload.id]:
                        payload = p_clone_buffer[payload.__class__][payload.id]
                    else:
                        print("cloning subnode %s[%d].%s.id -> [%d]" % (src.__class__, src.id, stream, payload.id))
                        clone = self.db_clone_with_changes(payload)
                        p_clone_buffer[payload.__class__][payload.id] = clone
                        payload = clone
            initprms[stream] = payload

        initprms = {**initprms, **repl}
        newoag = src.__class__(initprms=initprms, initschema=False).db.create()
        p_clone_buffer[src.__class__][src.id] = newoag

        return newoag

    def txnclone(self):

        global p_clone_buffer
        global p_domain

        p_clone_buffer = nested_dict()

        with OADbTransaction("Clone domain") as tran:

            n_domain = self.db_clone_with_changes(self.root_domain, repl={'version_name' : str()})

            # TODO: this can be inferred recursively from forward keys

            for site in self.root_domain.site:
                n_site = self.db_clone_with_changes(site)
                for host in site.host:
                    n_host = self.db_clone_with_changes(host)

                    # Clone interfaces recursively
                    for iface in host.net_iface:
                        n_iface = self.db_clone_with_changes(iface)

                    # Clone tunables
                    for tunable in host.sysctl:
                        n_tunable = self.db_clone_with_changes(tunable)

                    # Clone bare-metal capabilities
                    for cap in host.capability:
                        n_capability = self.db_clone_with_changes(cap)

            for depl in self.root_domain.deployment:
                n_depl = self.db_clone_with_changes(depl)
                if depl.capability:
                    for cap in depl.capability:
                        n_cap = self.db_clone_with_changes(cap)

                        if cap.capability_required_mount:
                            for crm in cap.capability_required_mount:
                                n_crm = self.db_clone_with_changes(crm)

                        if cap.capability_knob:
                            for ckb in cap.capability_knob:
                                n_ckb = self.db_clone_with_changes(ckb)

                        if cap.capability_alias:
                            for ca in cap.capability_alias:
                                n_ca = self.db_clone_with_changes(ca)

            for subnet in self.root_domain.subnet:
                n_subnet = self.db_clone_with_changes(subnet)

        self.root_domain.db.search()

        p_domain = n_domain

        return p_clone_buffer[self.__class__][self.id]

class OAG_Capability(OAG_FriezeRoot):
    """A capability is the running unit of work which is monitored and logged"""

    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def dbindices(cls): return {
        'host_capname' : [ ['host',       'service'], False, None ],
        'depl_capname' : [ ['deployment', 'service'], False, None ],
        'depl_strpgroup_capname'
                       : [ ['deployment', 'service', 'stripe_group'], False, None ],
    }

    @staticproperty
    def streamable(self): return True

    @staticproperty
    def streams(cls): return {
        'deployment'   : [ OAG_Deployment, False, None ],
        'affinity'     : [ OAG_Site,       False, None ],
        'host'         : [ OAG_Host,       False, None ],
        'service'      : [ 'text',         str(), None ],
        'stripe'       : [ 'int',          int(), None ],
        'stripe_group' : [ 'text',         True,  None ],
        'cores'        : [ 'float',        int(), None ],
        'memory'       : [ 'int',          int(), None ],
        'start_rc'     : [ 'bool',         None,  None ],
        'start_local'  : [ 'bool',         False, None ],
        'start_local_prms':
                        [ 'text',         None,  None ],
        'fib'          : [ FIB,            True,  None ],
        'expose'       : [ OAG_Site,       False, None ],
        'secure'       : [ 'bool',         True,  None ],
        'custom_pkg'   : [ 'bool',         False, None ],
    }

    @property
    def c_capability(self):
        return getattr(frieze.capability, self.service, None)

    def rc_delete(self):
        self.start_rc = None
        self.db.update()

    def rc_disable(self):
        self.start_rc =False
        self.db.update()

    def rc_enable(self):
        self.start_rc = True
        self.db.update()

    @property
    def fqdn(self):
        return f"{self.name}.{self.deployment.name}.{self.deployment.domain.domain}"

    @property
    def fqdn_ext(self):
        if self.capability_alias and self.capability_alias.is_external:
            return self.capability_alias.fqdn
        else:
            return None

    @property
    def fqdn_stripe(self):
        return f'{self.stripe_group}.{self.deployment.name}.{self.deployment.domain.domain}'

    @property
    def name(self):
        return "%s%d" % (self.service, self.stripe)

    @property
    def package(self):
        # In base?
        if self.c_capability:
            return self.c_capability.package
        else:
            return None

    @property
    def slot_factor(self):
        return (self.cores if self.cores else 0.25) * (self.memory if self.memory else 256)

    def truststore(self, pubkey=True, internal=False):
        """Return directory where certificates related to this capability are stored on disk"""
        if self.capability_alias and self.capability_alias.is_external:
            aliases = [ca.fqdn for ca in self.capability_alias]
        else:
            aliases = [self.fqdn]

        aliases.sort()

        inferred_name = hashlib.sha256(','.join(aliases).encode('utf-8')).hexdigest()

        return os.path.join(
            '/usr/local/etc/trust',
            'internal' if internal else 'external',
             inferred_name,
            'chain.crt' if pubkey else 'private.pem'
        )

class OAG_CapabilityAlias(OAG_FriezeRoot):
    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def dbindices(cls): return {
    }

    @staticproperty
    def streamable(self): return True

    @staticproperty
    def streams(cls): return {
        'capability'  : [ OAG_Capability, True,  None ],
        'alias'       : [ 'text',         True,  None ],
        'is_external' : [ 'boolean',      True,  None ],
    }

    @property
    def fqdn(self):
        return f'{self.alias}.{self.capability.deployment.domain.domain}' if self.alias else self.capability.deployment.domain.domain

class OAG_CapabilityKnob(OAG_FriezeRoot):

    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def dbindices(cls): return {
    }

    @staticproperty
    def streamable(self): return True

    @staticproperty
    def streams(cls): return {
        'capability' : [ OAG_Capability, True,  None ],
        'knob'       : [ 'text',         True,  None ],
        'value'      : [ 'text',         True,  None ],
    }

class OAG_CapabilityRequiredMount(OAG_FriezeRoot):

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

class OAG_CapabilityRole(OAG_FriezeRoot):
    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def streamable(self): return True

    @staticproperty
    def streams(cls): return {
        'capability'  : [ OAG_Capability, True, None ],
        'role'        : [ OAG_Role,       True, None ]
    }

class OAG_Container(OAG_FriezeRoot):

    class DataLayer(enum.Enum):
        RELEASE  = 1
        BASE     = 2
        SKELETON = 3
        THINJAIL = 4

    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def streamable(cls): return False

    @staticproperty
    def streams(cls): return {
        'capability'  : [ OAG_Capability,  True,  None ],
        'site'        : [ OAG_Site,        True,  None ],
        'host'        : [ OAG_Host,        True,  None ],
        'deployment'  : [ OAG_Deployment,  True,  None ],
        # The order in which this item was placed on this host
        'seqnum'      : ['int',            True,  None ],
    }

    @property
    def block_storage(self):
        return OAG_SysMount() if self.site.block_storage.size==0 else self.site.block_storage.clone().rdf.filter(lambda x: x.container_name==self.fqdn)

    @property
    def configprovider(self):
        return {
            OSFamily.FreeBSD : ConfigGenFreeBSD,
        }[self.host.os.family](self)

    def configure(self, targetdir=None):
        return ConfigInit(self.configprovider.intermediate_representation).generate(targetdir=targetdir)

    def dataset(self, layer, mountpoint=False):
        dsname = {
            Container.DataLayer.RELEASE : f'release/{self.os.release_name}',
            Container.DataLayer.BASE:     f'base/{self.os.release_name}',
            Container.DataLayer.SKELETON: f'skeleton/{self.os.release_name}',
            Container.DataLayer.THINJAIL: f'thinjail/{self.deployment.name}/{self.capability.name}'
        }[layer]

        if not mountpoint:
            return f'zroot/jails/{dsname}'
        else:
            return f'/usr/local/jails/{dsname}'

    @property
    def fqdn(self):
        return self.capability.fqdn

    def ip4(self):
        """Find appropriate VLAN and dynamically generate this container's
        IP address based on its host subnet sequence number"""
        for iface in self.host.internal_ifaces:
            if self.deployment.vlan!=iface.name:
                continue
            return str(iface.subnet.ip4network[self.seqnum+1])

    @property
    def jaildir(self):
        return f'/usr/local/jails/{self.deployment.name}/{self.capability.name}'

    @property
    def name(self):
        return self.capability.name

    @property
    def os(self):
        """For now, only support jails that are the same as host os"""
        return self.host.os

    @property
    def stripe_group(self):
        return self.capability.stripe_group

    @property
    def sysname(self):
        return f'{self.deployment.name}_{self.capability.name}'

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
        'seqnum'   : [ 'int',      True,  None ],
        'name'     : [ 'text',     True,  None ],
    }

    @friezetxn
    def add_capability(self, capdef, enable_state=True, affinity=None, stripes=1, stripe_group=None, max_stripes=None, expose=None, external_alias=[], secure=False, custom_pkg=False, acls=[]):
        """ Where should we put this new capability? Loop through all
        hosts in site and see who has slots open. One slot=1 cpu + 1GB RAM.
        If capdef doesn't specify cores or memory required, just go ahead
        and put it on the first host with ANY space on it.

        Also check to make sure that the capability can be containerized,
        and throw if it cannot"""
        if isinstance(capdef, CapabilityTemplate):

            if not capdef.jailable:
                raise OAError(f"Capability [{capdef.name}] is not jailable and cannot be added to deployment")
            if expose and not external_alias:
                raise OAError(f"Exposed capability [{capdef.name}] *must* have external DNS alias")

            stripe_group = capdef.name if not stripe_group else stripe_group

            # Determine what the overall stripe count should be for this service,
            # and further determine if we have created too many stripes for this
            # stripe group
            try:
                cap = OAG_Capability((self, capdef.name), 'by_depl_capname')
                stripe_base = cap[-1].stripe+1
            except:
                stripe_base = 0

            try:
                cap = OAG_Capability((self, capdef.name, stripe_group), 'by_depl_strpgroup_capname')
                if max_stripes and cap.size>=max_stripes:
                    print(f"====> [{self.name}] All necessary [{capdef.name}] stripes for stripe group [{stripe_group}] already running (max {max_stripes})")
                    return self
            except OAGraphRetrieveError:
                pass

            with OADbTransaction("App Add"):
                for stripe in range(stripes):
                    cap =\
                        OAG_Capability().db.create({
                            'deployment' : self,
                            'host' : None,
                            'service' : capdef.name,
                            'stripe' : stripe_base+stripe,
                            'stripe_group' : stripe_group,
                            'affinity' : affinity,
                            'cores' : capdef.cores if capdef.cores else 0,
                            'memory' : capdef.memory if capdef.memory else 0,
                            'start_rc' : enable_state,
                            'start_local' : False,
                            # OK to set FIB.DEFAULT: containerized capabilities
                            # are always on the default (internal) routing table
                            'fib' : FIB.DEFAULT,
                            'expose' : expose,
                            'secure' : secure,
                            'custom_pkg' : custom_pkg,
                        })

                    if capdef.setknobs_exist:
                        for knob, value in capdef.set_knobs.items():
                            knob =\
                                OAG_CapabilityKnob().db.create({
                                    'capability' : cap,
                                    'knob' : knob,
                                    'value' : value
                                })

                    for alias in external_alias:
                        capalias =\
                            OAG_CapabilityAlias().db.create({
                                'capability' : cap,
                                'alias' : alias,
                                'is_external' : True
                            })

                    for acl in set(acls):
                        caprole =\
                            OAG_CapabilityRole().db.create({
                                'capability' : cap,
                                'role'       : OAG_Role((self.domain, acl), 'by_name')[-1]
                            })

                    for (mount, size_gb) in capdef.mounts:
                        capmount =\
                            OAG_CapabilityRequiredMount().db.create({
                                'cap' : cap,
                                'mount' : mount,
                                'size_gb' : size_gb,
                            })
        else:
            raise OAError("AppGroups not yet supported")

        return self

    @property
    def containers(self):
        return self.domain.containers.clone().rdf.filter(lambda x: x.deployment.id==self.id)

    @property
    def revzone(self):
        return '%d.10.in-addr.arpa' % (self.seqnum)

    @property
    def rununits(self):
        return self.containers

    @property
    def vlan(self):
        return 'vlan%d' % (self.vlanid-1)

    @property
    def vlanid(self):
        return self.seqnum+1

    @property
    def zone(self):
        return '%s.%s' % (self.name, self.domain.domain)

class OAG_Domain(OAG_FriezeRoot):
    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def dbindices(cls): return {
        'domain'        : [ ['domain'],                 False,  None ],
        'version_name'  : [ ['domain', 'version_name'], True,   None ]
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
            depl = OAG_Deployment((self, name), 'by_name')[-1]
            print(f"====> Found previously generated entry for deployment [{name}]")
        except OAGraphRetrieveError:
            print(f"====> Creating new entry for deployment [{name}]")
            try:
                seqnum = self.deployment.size
            except AttributeError:
                seqnum = 0

            depl =\
                OAG_Deployment().db.create({
                    'domain'    : self,
                    'seqnum'    : seqnum,
                    'name'      : name
                })

            for site in self.site:
                for host in site.host:
                    host.add_iface(depl.vlan, False, hostiface=host.internal_ifaces[0], type_=NetifType.VLAN, deployment=depl)

        return depl

    @friezetxn
    def add_role(self, username, password=None, ssl_enabled=False):
        try:
            role = OAG_Role((self, 'username'), 'by_name')
        except OAGraphRetrieveError:
            if not password:
                password=base64.b16encode(os.urandom(16)).decode('ascii')
            role =\
                OAG_Role().db.create({
                    'domain'   : self,
                    'username' : username,
                    'password' : password
                })
        return self

    @friezetxn
    def add_site(self, sitename, shortname, provider, location):
        try:
            site = OAG_Site((self, sitename), 'by_name')[-1]
            print(f"====> Found previously generated entry for site [{sitename}]")
        except OAGraphRetrieveError:
            print(f"====> Creating new entry for site [{sitename}]")
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
    def assign_subnet(self, type_, hosts_expected=254, iface=None, dynamic_hosts=0, deployment=None):


        # Calculate smallest possible prefix that can accommodate number of
        # hosts expected.
        def hosts_to_prefix(hostcount, prefix__=8):
            while hostcount<=pow(2, 32-prefix__)-2:
                prefix__+=1
            return prefix__-1

        prefixlen = hosts_to_prefix(hosts_expected)

        if type_ in (SubnetType.ROUTING, SubnetType.SITE):
            root_network    = '172.16.0.0'
            root_prefixlen  =  12
        else:
            root_network    = '10.%d.0.0' % deployment.seqnum
            root_prefixlen  =  16

        root_subnet = ipaddress.IPv4Network('%s/%s' % (root_network, root_prefixlen))

        # How many of subnets sized prefixlen are there in root_subnet
        candidate_subnets = root_subnet.subnets(prefixlen_diff=prefixlen-root_prefixlen)
        existing_subnets = []
        try:
            existing_subnets = [esub.ip4network for esub in self.subnet.rdf.filter(lambda x: x.type==type_)]
        except AttributeError:
            pass

        for csubnet in candidate_subnets:
            overlap_found = False
            for esub in existing_subnets:
                if csubnet.overlaps(esub):
                    overlap_found = True
            if not overlap_found:
                break

        # Degenerate case: we don't have any subnets left
        if overlap_found:
            raise OAError("Subnet exhaustion")

        self.db.search()

        return\
            OAG_Subnet().db.create({
                'domain'        : self,
                'network'       : str(csubnet.network_address),
                'prefixlen'     : int(csubnet.prefixlen),
                'type'          : type_.value,
                'router'        : iface.host if iface else None,
                'routing_iface' : iface,
                'dynamic_hosts' : dynamic_hosts
            })

    def trust(self, trust_type=TrustType.INTERNAL):
        return {
            TrustType.INTERNAL    : CertAuthInternal,
            TrustType.LETSENCRYPT : CertAuthLetsEncrypt
        }[trust_type](self)

    @oagprop
    def containers(self, **kwargs):
        """Global view of jobs. Can be filtered by OAG_Deployment or OAG_Site
        to determine what the distribution of containers currently is"""

        def init_resource_matrix():
            rmatrix = {}
            for site in self.site:
                try:
                    rmatrix[site.shortname]
                except KeyError:
                    rmatrix[site.shortname] = {}

                for i, host in enumerate(site.compute_hosts):
                    try:
                        rmatrix[site.shortname][host.fqdn]
                    except KeyError:
                        rmatrix[site.shortname][host.fqdn] = {
                            # Total number of containers on this host -per deployment-
                            'depl_count'       : dict(),
                            # Total number of containers on this host
                            'container_count'  : 0,
                            'oag'              : host.clone()[i],
                            'slot_factor'      : host.memory * host.cores
                        }
            return rmatrix

        def bin_capability_in_resource_matrix(cap, site, hostname, deployment, o_rmatrix):
            o_rmatrix[site][hostname]['slot_factor'] -= cap.slot_factor
            o_rmatrix[site][hostname]['container_count'] += 1

            try:
                o_rmatrix[site][hostname]['depl_count'][depl.name]
            except KeyError:
                o_rmatrix[site][hostname]['depl_count'][depl.name] = 0
            o_rmatrix[site][hostname]['depl_count'][depl.name] +=1

        rmatrix = init_resource_matrix()

        # Containers are placed deployment first, site second. Affinity free
        # definitions are placed wherever there is room. If resources are not
        # available, they are not entered in the capability mapping
        containers = [list(OAG_Container.streams.keys())]
        unplaceable_caps = []
        for depl in self.deployment:

            if depl.capability:

                # Place site specific capabilities first
                caps_with_affinity = depl.capability.clone().rdf.filter(lambda x: x.affinity is not None)
                for cap in caps_with_affinity:
                    site_slot_factor = sum([host['slot_factor'] for hostname, host in rmatrix[cap.affinity.shortname].items()])
                    if site_slot_factor<cap.slot_factor:
                        unplaceable_caps.append((cap.affinity.id, cap.fqdn))
                        continue

                    for hostname, host in rmatrix[cap.affinity.shortname].items():
                        if host['slot_factor']-cap.slot_factor>=0:
                            bin_capability_in_resource_matrix(cap, cap.affinity.shortname, hostname, depl, rmatrix)
                            containers.append([
                                cap.clone(),
                                site.clone(),
                                host['oag'].clone(),
                                depl.clone(),
                                rmatrix[cap.affinity.shortname][hostname]['depl_count'][depl.name],
                            ])
                            break

                # Distribute affinity-free resources next
                caps_without_affinity = depl.capability.clone().rdf.filter(lambda x: x.affinity is None)
                for cap in caps_without_affinity:
                    site_loop_break = False

                    domain_slot_factor = 0
                    for site, hostinfo in rmatrix.items():
                        domain_slot_factor += sum([host['slot_factor'] for hostname, host in hostinfo.items()])
                    if domain_slot_factor<cap.slot_factor:
                        unplaceable_caps.append(('no-affinity', cap.fqdn))
                        continue

                    for site, hostinfo in rmatrix.items():
                        if site_loop_break:
                            break
                        for hostname, host in hostinfo.items():
                            if host['slot_factor']-cap.slot_factor>=0:
                                bin_capability_in_resource_matrix(cap, site, hostname, depl, rmatrix)
                                containers.append([
                                    cap.clone(),
                                    OAG_Site((self, site), 'by_shortname')[0],
                                    host['oag'].clone(),
                                    depl.clone(),
                                    rmatrix[site][hostname]['depl_count'][depl.name],
                                ])
                                site_loop_break = True
                                break

        if len(unplaceable_caps)>0:
            print("Warning: unable to place the following caps:")
            pprint(unplaceable_caps)

        return OAG_Container(initprms=containers)

    def deploy(self, push=True, version_name=str()):

        if not self.is_frozen:
            raise OAError("Can't deploy domain that hasn't been snapshotted")

        def generate_domain_config():
            hostcfgs = {}
            for site in self.site:
                hostcfgs = {**hostcfgs, **site.configure()}
            return hostcfgs

        # If you aren't pushing, just generate the files and return
        if not push:
            generate_domain_config()
            return

        # Atomically distribute the cert authority to all sites so that
        # we can link them to the servers that are going to be set up
        # shortly
        self.trust().distribute_authority()

        # Issue command to create hosts, networking between them, and
        # storage.
        for site in self.site:
            site.prepare_infrastructure()

        # Update external DNS to make sure all services are visible. This
        # has to be after infrastructure is prepared to ensure clean IP
        # information is available for machines.
        self.extdns.distribute()

        # Issue SSH credential and use it to push to all hosts. Wrap in tempfile
        # to ensure that files are wiped out after context manager __exit__s.
        with tempfile.TemporaryDirectory() as td:

            # Generate configs
            hostcfgs = generate_domain_config()

            # SSH credential creation
            (id_file, id_file_pub) =\
                self.trust().issue_certificate(
                    pwd.getpwuid(os.getuid())[0],                       # subject
                    CertAction.HOST_ACCESS_AUTO.desc(
                        info=f'[{self.domain}:{self.version_name}]'
                    ),
                    serialize_to_dir=os.path.join(td, '.ssh')           # where to serialize
                )

            # get configinit representation, send to host for execution
            for host, host_tar in hostcfgs.items():
                remote_address = host.db.search()[-1].ip4(fib=FIB.WORLD)
                remote_tarfile = f'{host.fqdn}.tar.bz2'
                cmd = f'ssh root@{remote_address} -i {id_file} "cat > {remote_tarfile} && configinit {remote_tarfile}"'

                print(f'Pushing configuration for: {host.fqdn} ({remote_address})')
                print(f'  {cmd}')

                output =\
                    subprocess.run(
                        cmd,
                        shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        input=host_tar
                    )

                # We'll need to log output here
                print(output)

    @oagprop
    def extdns(self, **kwargs):
        return ExtDNS(self)

    @property
    def is_frozen(self):
        return len(self.version_name)>0

    def snapshot(self, version_name):
        if self.version_name:
            raise OAError("This version has already been snapshot with [%s]" % self.version_name)

        try:
            version = OAG_Domain((self.domain, version_name), 'by_version_name')
            raise OAError(f"Snapshot [{version_name}] already exists")
        except OAGraphRetrieveError:
            self.version_name = version_name
            self.db.update()

        return self

class OAG_Host(OAG_FriezeRoot):

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
        'cores'     : [ 'int',    True, None ],
        'memory'    : [ 'int',    True, None ],
        'bandwidth' : [ 'int',    True, None ],
        'name'      : [ 'text',   True, None ],
        'role'      : [ HostRole, True, None ],
        'os'        : [ HostOS,   True, None ],
        # Enrichment information from cloud provider
        'c_ip4'     : [ 'text',   None, None ],
        'c_gateway' : [ 'text',   None, None ],
        'c_netmask' : [ 'text',   None, None ],
    }

    @friezetxn
    def add_capability(self, capdef, enable_state=None, fib=FIB.DEFAULT, custom_pkg=False):
        """Run a capability on a host. Enable it."""
        if isinstance(capdef, CapabilityTemplate):
            create = True
            try:
                cap = OAG_Capability((self, capdef.name), 'by_host_capname')
                create = False
            except OAGraphRetrieveError:
                pass

            with OADbTransaction("App Add"):
                if create:
                    cap =\
                        OAG_Capability().db.create({
                            'deployment' : None,
                            'host' : self,
                            'service' : capdef.name,
                            'stripe' : 0,
                            'stripe_group' : capdef.name,
                            'affinity' : None,
                            'cores' : capdef.cores if capdef.cores else 0,
                            'memory' : capdef.memory if capdef.memory else 0,
                            'start_rc' : enable_state,
                            'start_local' : False,
                            'fib' : fib,
                            'expose' : False,
                            'secure' : False,
                            'custom_pkg' : custom_pkg,
                        })

                    if capdef.setknobs_exist:
                        for knob, value in capdef.set_knobs.items():
                            knob =\
                                OAG_CapabilityKnob().db.create({
                                    'capability' : cap,
                                    'knob' : knob,
                                    'value' : value
                                })

                    if capdef.mounts:
                        raise OAError("Mounts not supported for baremetal caps")
        else:
            raise OAError("AppGroups not yet supported")

        return self

    @friezetxn
    def add_iface(self, name, is_external, fib=FIB.DEFAULT, hostiface=None, type_=NetifType.PHYSICAL, mac=str(), wireless=False, deployment=None):

        try:
            iface = OAG_NetIface((self, name), 'by_name')
        except OAGraphRetrieveError:
            iface =\
                OAG_NetIface(initprms={
                    'host'        : self,
                    'name'        : name,
                    'type'        : type_,
                    'mac'         : mac,
                    'fib'         : fib,
                    'is_external' : is_external,
                    'wireless'    : wireless,
                    'deployment'  : deployment,
                })

            # If it's a VLAN, fib is the same is the host interface
            if type_==NetifType.VLAN:
                if not hostiface:
                    raise OAError("Need a parent interface to associate VLAN with")
                if hostiface.fib != fib:
                    raise OAError("Parent interface has different fib from given one")
                if hostiface.is_external:
                    raise OAError("Can't put a VLAN on an external interface")

                iface.fib      = hostiface.fib
                iface.vlanhost = hostiface

            # See if this interface is being routed by another interface
            if type_==NetifType.PHYSICAL and not self.is_bastion and not iface.is_external:
                iface.routed_by = self.site.bastion.routed_subnets[self.internal_ifaces.size].routing_iface

            iface.db.create()

            self.db.search()

            # Don't forget the second order effects:
            # 1. Rerouting traffic if adding internal interface on bastion
            if iface.type==NetifType.PHYSICAL and self.is_bastion and not iface.is_external:
                if self.site.compute_hosts:
                    for host in self.site.compute_hosts:
                        for i, int_iface in enumerate(host.internal_ifaces):
                            try:
                                int_iface.routed_by = self.site.bastion.routed_subnets[i].routing_iface
                                int_iface.fib = FIB.DEFAULT
                                int_iface.db.update()
                            except IndexError:
                                raise OAError("Unable to find corresponding internal routing interface")
                self.site.domain.assign_subnet(SubnetType.SITE, hosts_expected=1000, iface=iface, dynamic_hosts=100)

            # 2. Assign subnets to VLAN that is being created
            if iface.type==NetifType.VLAN:
                self.site.domain.assign_subnet(
                    SubnetType.DEPLOYMENT,
                    deployment=deployment,
                    hosts_expected=1 if self.is_bastion else 14,
                    iface=iface
                )

            # 3. Assign networking capabilities: dhclient to be specific.
            dhcp_ifaces = self.physical_ifaces.rdf.filter(lambda x: x.routingstyle==RoutingStyle.DHCP)
            if dhcp_ifaces.size>1 and len(self.fibs)>1:

                # Update previously created dhclient capabilities
                updated = 0
                dhclients = self.capability.rdf.filter(lambda x: x.service=='dhclient') if self.capability else []
                for i, dhclient in enumerate(dhclients):
                    try:
                        dhclient.db.update({
                            'start_rc' : False,
                            'start_local' : True,
                            'start_local_prms' : dhcp_ifaces[i].name,
                            'fib' : self.fibs[updated]
                        })
                    except Exception as e:
                        print(e)
                        raise
                    updated += 1

                # Create remaining required dhclients (i.e. for current interface)
                for i in range(updated, len(self.fibs)):
                    OAG_Capability().db.create({
                        'deployment' : deployment,
                        'host' : self,
                        'service' : dhc.name,
                        'stripe' : 0,
                        'stripe_group' : dhc.name,
                        'affinity' : None,
                        'cores' : dhc.cores if dhc.cores else 0,
                        'memory' : dhc.memory if dhc.memory else 0,
                        'start_rc' : False,
                        'start_local' : True,
                        'start_local_prms' : dhcp_ifaces[i].name,
                        'fib' : self.fibs[i],
                        'expose' : False,
                        'secure' : False,
                        'custom_pkg' : False,
                    })

            # 4. Enable dhcpd on bastion (if it exists) -every- time because each newly added interface
            #    can potentially trigger a dhcpd requirement. Same for named, I guess.
            if self.site.bastion:
                bastion = self.site.bastion

                # DHCP
                try:
                    cap_dhcpd = bastion.capability.rdf.filter(lambda x: x.service=='dhcpd') if bastion.capability else bastion.capability
                except AttributeError:
                    cap_dhcpd = None
                dhcpd_ifaces = ' '.join([iface.name for iface in bastion.internal_ifaces if iface.dhcpd_enabled])
                if not cap_dhcpd:
                    dhcpd_capdef = dhcpd().setknob('ifaces', dhcpd_ifaces)
                    bastion.add_capability(dhcpd_capdef, enable_state=True)
                else:
                    dhcpd_iface_knob = cap_dhcpd.capability_knob.rdf.filter(lambda x: x.knob=='ifaces')
                    if dhcpd_ifaces != dhcpd_iface_knob.value:
                        dhcpd_iface_knob.db.update({
                            'value' : dhcpd_ifaces
                        })

                # DNS
                bastion.add_capability(named(), enable_state=True)

                # Turn off cloud-provided resolvconf
                for host in self.site.host:
                    host.add_capability(resolvconf())

            # 5. If this is an internal interface, enable bird
            if not iface.is_external:
                self.add_capability(bird(), enable_state=True)

        return self

    @property
    def block_storage(self):
        return OAG_SysMount() if self.site.block_storage.size==0 else self.site.block_storage.clone().rdf.filter(lambda x: x.host.fqdn==self.fqdn)

    @property
    def configprovider(self):
        return {
            OSFamily.FreeBSD : ConfigGenFreeBSD,
        }[self.os.family](self)

    def configure(self, targetdir):
        return ConfigInit(self.configprovider.intermediate_representation).generate(targetdir=targetdir)

    @property
    def containers(self):
        return self.site.domain.clone()[-1].containers.rdf.filter(lambda x: x.host.id==self.id)

    def default_gateway(self, fib=FIB.DEFAULT):
        for iface in self.physical_ifaces:
            if self.role==HostRole.SITEBASTION:
                if iface.is_external:
                    return iface
            else:
                if not iface.is_external and iface.fib==fib:
                    return iface

    @property
    def domain(self):
        return self.site.domain

    @oagprop
    def fibs(self, **kwargs):
        if self.role==HostRole.SITEBASTION:
            return [FIB.DEFAULT]
        else:
            return [iface.fib for iface in self.physical_ifaces.clone()]

    @property
    def fqdn(self):
        return '%s.%s' % (self.name, self.site.zone)

    @property
    def internal_ifaces(self):
        return self.net_iface.clone().rdf.filter(lambda x: x.is_external is False)

    def ip4(self, fib=FIB.DEFAULT):
        """Depending on specified FIB, return relevant IP address. DEFAULT:
        return IP address of internal interface; WORLD means return IP address
        provided by cloud provider on external interface"""
        if fib==FIB.DEFAULT:
            return self.internal_ifaces[0].ip4
        else:
            return self.c_ip4 if self.c_ip4 else str()

    @property
    def physical_ifaces(self):
        return self.net_iface.clone().rdf.filter(lambda x: x.type==NetifType.PHYSICAL)

    @property
    def is_bastion(self):
        return self.role==HostRole.SITEBASTION

    @property
    def revzone(self):
        return '%s.in-addr.arpa' % '.'.join(reversed(self.ip4().split('.')[:3]))

    @property
    def rootdisk(self):
        return ExtCloud(self.site.provider).block_rootdisk()

    @property
    def routed_subnets(self):
        return self.subnet.clone()

    @property
    def stripe_group(self):
        return None

class OAG_NetIface(OAG_FriezeRoot):

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
        'type'        : [ NetifType,    True,  None ],
        'mac'         : [ 'text',       None,  None ],
        # Is connected to the internet
        'is_external' : [ 'boolean',    False, None ],
        # Routing table to default to
        'fib'         : [ FIB,          None,  None ],
        # Is wireless
        'wireless'    : [ 'boolean',    True,  None ],
        # Interface is part of a bridge
        'bridge'      : [ OAG_NetIface, False, None ],
        # Interface is a VLAN cloned off a parent interface
        'vlanhost'    : [ OAG_NetIface, False, None ],
        # Interface which routes traffic from this interface
        'routed_by'   : [ OAG_NetIface, False, None ],
        # Deployment
        'deployment'  : [ OAG_Deployment, False, None ]
    }

    @property
    def bird_enabled(self):
        return not self.is_external

    @oagprop
    def bridge_members(self, **kwargs):
        if self.type==NetifType.BRIDGE:
            return self.net_iface_bridge
        else:
            OAError("Non-bridge interfaces can't have bridge members")

    @property
    def routed_subnet(self):
        if self.routed_by:
            return self.routed_by.subnet[-1]

        if self.routingstyle==RoutingStyle.STATIC:
            try:
                return self.subnet[-1]
            except TypeError:
                pass

        return None

    @property
    def broadcast(self):
        if self.is_external:
            if not self.host.c_ip4:
                return None
            else:
                prefix = ipaddress.IPv4Address(int(ipaddress.IPv4Address(self.host.c_ip4)) & int(ipaddress.IPv4Address(self.host.c_netmask)))
                return ipaddress.IPv4Network(f'{prefix}/{self.host.c_netmask}').broadcast_address
        else:
            return self.routed_subnet.broadcast if self.routed_subnet else None

    @property
    def connected_ifaces(self):
        """Generate IP addressing map on the fly for a given routing interface.

        Return the map keyed by inferred name for easy lookup by other interfaces
        trying to learn their IP address. See @property ip4 for example on use."""
        return {nif.infname:self.routed_subnet[-1].ip4network[i+2] for i, nif in enumerate(self.net_iface_routed_by)}

    @property
    def dhcpd_enabled(self):
        return self.host.is_bastion and not self.is_external and not self.type==NetifType.VLAN

    @property
    def gateway(self):
        if self.is_external:
            return self.host.c_gateway
        else:
            return self.routed_subnet.gateway if self.routed_subnet else None

    @property
    def ip4(self):

        rv = None

        if self.is_external:
            rv = self.host.c_ip4
        else:
            if self.routingstyle==RoutingStyle.STATIC:
                # This is an interface responsible for assigning IP addresses
                # to other interfaces on the subnet so its IP address is that
                # of the subnet it is routing.
                rv = str(self.routed_subnet.gateway) if self.routed_subnet else None
            else:
                # Only assign IP address to routers that are being routed by
                # another interface.
                if self.routed_by:
                    rv = str(self.routed_by.connected_ifaces[self.infname])

        return rv

    @property
    def is_gateway(self):
        return self.gateway is None

    @property
    def mtu(self):
        """Return None if interface autonegotiates, otherwise value returned by
        cloud provider"""
        return ExtCloud(self.host.site.provider).network_iface_mtu(external=self.is_external)

    @property
    def netmask(self):

        rv = None

        if self.is_external:
            rv = self.host.c_netmask
        else:
            if self.routingstyle==RoutingStyle.STATIC:
                # This is an interface responsible for assigning IP addresses
                # to other interfaces on the subnet so its IP address is that
                # of the subnet it is routing.
                rv = str(self.routed_subnet.netmask) if self.routed_subnet else None
            else:
                # Only assign IP address to routers that are being routed by
                # another interface.
                if self.routed_by:
                    rv = str(self.routed_by.connected_ifaces[self.infname].netmask)
        return rv

    @property
    def routingstyle(self):
        if self.is_external:
            return RoutingStyle.DHCP
        else:
            if self.host.site.bastion:
                if self.host.is_bastion:
                    return RoutingStyle.STATIC
                else:
                    if self.type==NetifType.PHYSICAL:
                        return RoutingStyle.DHCP
                    else:
                        return RoutingStyle.STATIC
            else:
                return RoutingStyle.UNROUTED

    @oagprop
    def vlans(self, **kwargs):
        if self.type==NetifType.PHYSICAL:
            return self.net_iface_vlanhost
        else:
            OAError("Non-physical interfaces can't clone vlans")

    @staticproperty
    def formatstr(self): return "    %-10s|%-23s|%-17s|%-10s|%-10s|%-10s|%-15s|%-15s|%-15s"

    def summarize(self):
        """Purely informational, shouldn't appear anywhere in production code!"""

        print(self.formatstr % (
            self.name,
            self.routingstyle,
            self.fib,
            self.bird_enabled,
            self.dhcpd_enabled,
            self.is_gateway,
            self.ip4,
            self.gateway,
            self.broadcast))

class OAG_Role(OAG_FriezeRoot):

    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def dbindices(cls): return {
        'name'        : [ ['domain', 'username'], True, None ],
    }

    @staticproperty
    def streamable(self): return True

    @staticproperty
    def streams(cls): return {
        'domain'      : [ OAG_Domain,   True,  None ],
        'username'    : [ 'text',       True,  None ],
        'password'    : [ 'text',       True,  None ],
    }

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
        'domain'    : [ OAG_Domain,     True,  None ],
        'name'      : [ 'text',         str(), None ],
        'shortname' : [ 'text',         str(), None ],
        'provider'  : [ CloudProvider,  True,  None ],
        'location'  : [ Location,       True,  None ],
    }

    @friezetxn
    def add_host(self, template, name, role):
        try:
            host = OAG_Host((self, name), 'by_name')[-1]
            print(f"====> Found previously generated entry for [{host.fqdn}]")
        except OAGraphRetrieveError:
            print(f"====> Creating new entry for [{name}]")
            host =\
                OAG_Host().db.create({
                    'site' : self,
                    'cores' : template.cores,
                    'memory' : template.memory,
                    'bandwidth' : template.bandwidth,
                    'name' : name,
                    'role' : role,
                    'os' : template.os
                })

            # Add network interfaces
            for iface in template.interfaces:
                host.add_iface(iface[0], iface[1], fib=iface[2] if len(iface)>2 else FIB.DEFAULT)

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

            # Turn on forwarding and pf by default: EVERY host is a router
            host.add_capability(firstboot())
            host.add_capability(gateway(), enable_state=True)
            host.add_capability(pf(), enable_state=True)
            host.add_capability(pflog(), enable_state=True)
            if host.role==HostRole.SITEBASTION:
                host.add_capability(pflate(), enable_state=True)
            host.add_capability(zfs(), enable_state=True)
            if host.role==HostRole.COMPUTE:
                host.add_capability(jail(), enable_state=True)

            # On host (i.e. bare metal, non-jailed) processes
            for cap in template.caps:
                try:
                    kwargs = {}

                    (capability, enabled, externally_accessible) = cap

                    # Determine FIB information, set enable status accordingly
                    fibs = [FIB.WORLD] if (externally_accessible and len(host.fibs)>1) else host.fibs
                    if len(fibs)>1:
                        kwargs['enable_state'] = False
                    else:
                        kwargs['enable_state'] = enabled

                    for fib in fibs:
                        kwargs['fib'] = fib
                        host.add_capability(capability(), **kwargs)
                except ValueError:
                    (capability, enabled) = cap
                    host.add_capability(capability(), enable_state=enabled)

        return host

    @property
    def bastion(self):
        sitebastions = self.clone()[-1].host.rdf.filter(lambda x: x.is_bastion)
        if sitebastions.size==1:
            return sitebastions
        else:
            return None

    @oagprop
    def block_storage(self, **kwargs):
        """Analyzes containers on site and returns an OAG_BlockStore object
        listing block storage devices that need to be provided in order to run
        the site"""
        store_init = [['container_name', 'capmnt', 'host']]
        for container in self.containers:
            for cap in container.capability:
                try:
                    if cap.capability_required_mount:
                        for crm in cap.capability_required_mount:
                            store_init.append([container.fqdn, crm.clone(), container.host.clone()])
                except AttributeError:
                    # No caps pointed here yet
                    pass

        return OAG_SysMount() if len(store_init)==1 else OAG_SysMount(initprms=store_init)

    @property
    def compute_hosts(self):
        compute_hosts = self.host.clone().rdf.filter(lambda x: not x.is_bastion)
        if compute_hosts.size>0:
            return compute_hosts
        else:
            return None

    def configure(self):

        # Decide on directory to output files to
        version_dir = os.path.join(openarc.env.getenv('frieze').runprops.home, 'domains', self.domain.domain, 'deploy', self.domain.version_name)

        # Create configurations for each host. The configurations contain a
        # full suite of config files,
        hostcfgs = {}

        for i, host in enumerate(self.host.db.search()):

            # Fresh start: host config directory
            host_cfg_dir = os.path.join(version_dir, host.fqdn)
            try:
                shutil.rmtree(host_cfg_dir)
            except FileNotFoundError:
                pass

            hostcfgs[OAG_Host(host.id)] = host.configure(host_cfg_dir)

        return hostcfgs

    @property
    def containers(self):
        return self.domain.clone()[-1].containers.rdf.filter(lambda x: x.site.id==self.id)

    def prepare_infrastructure(self):

        # Prep the external provider
        extcloud = ExtCloud(self.provider)

        # Create your server configinit tarball
        cfi_push = firstboot().generate_bootstrap_tarball()
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
                    'c_ip4'     : c_srv['ip4'],
                    'c_gateway' : c_srv['gateway4'],
                    'c_netmask' : c_srv['netmask4']
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
                    'c_ip4'     : c_srv['ip4'],
                    'c_gateway' : c_srv['gateway4'],
                    'c_netmask' : c_srv['netmask4']
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

    @property
    def rununits(self):
        return self.host

    @property
    def zone(self):
        return('%s.%s' % (self.shortname, self.domain.domain))

    @oagprop
    def expose_map(self, **kwargs):
        expose_map = {}
        for cap in self.capability_expose:
            for depl in self.domain.deployment:
                for container in depl.containers:
                    if cap.fqdn==container.capability.fqdn:
                        for port in cap.c_capability.ports:
                            expose_map.setdefault(str(port), []).append(container.capability.fqdn_stripe)
        return expose_map

class OAG_Subnet(OAG_FriezeRoot):
    """Subnets are doled out on a per-domain basis and then assigned to
    assigned to a site."""
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
        'network'       : [ 'text',       str(), None ],
        'prefixlen'     : [ 'int',        int(), None ],
        # what is this subnet used for?
        'type'          : [ SubnetType,   True,  None ],
        'router'        : [ OAG_Host,     False, None ],
        'routing_iface' : [ OAG_NetIface, False, None ],
        'dynamic_hosts' : [ 'int',        True,  None ],
    }

    @property
    def netmask(self):
        return self.ip4network.netmask

    @property
    def broadcast(self):
        return self.ip4network.broadcast_address

    @property
    def dynamic_range(self):
        """Assign dynamic range from "top" of subnet. Return set of min and max
        of range"""
        if self.dynamic_hosts:
            return (self.ip4network[-2-(self.dynamic_hosts-1)], self.ip4network[-2])
        else:
            return ()

    @property
    def gateway(self):
        return self.ip4network[1]

    @property
    def ip4network(self):
        return ipaddress.IPv4Network('%s/%s' % (self.network, self.prefixlen))

    @property
    def with_prefixlen(self):
        return self.ip4network.with_prefixlen

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

class OAG_SysMount(OAG_FriezeRoot):

    @staticproperty
    def context(cls): return "frieze"

    @staticproperty
    def streamable(cls): return False

    @staticproperty
    def streams(cls): return {
        'container_name' : [ 'text',   True, None ],
        'capmnt'         : [ OAG_CapabilityRequiredMount, True, None ],
        'host'           : [ OAG_Host, True, None ]
    }

    @property
    def blockstore_name(self):
        """Device name on the cloud provider"""
        return f'{self.host.site.shortname}:{self.container_name}:{self.capmnt.mount}'

    @property
    def sysname(self):
        """Device name seen by OS when attached"""
        (disk_type, disk_root_idx) = self.host.rootdisk
        return f'/dev/{disk_type}{disk_root_idx+self._iteridx}'

    @property
    def dataset(self):
        return f'{self.zpool}'

    @property
    def default_mountdir(self):
        return '/mnt'

    @property
    def mount_point(self):
        return f'{self.default_mountdir}/{self.dataset}'

    @property
    def zpool(self):
        return f'{self.capmnt.cap.service}{self.capmnt.cap.stripe}_{self.capmnt.mount}'

####### Exportable friendly names go here

Host = OAG_Host
Netif = OAG_NetIface
Domain = OAG_Domain
Site = OAG_Site
Deployment = OAG_Deployment
Container = OAG_Container

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
    # Mount dedicated, encrypted ZFS dataset at ${FRIEZE}/database
    # Start pg database instance from ${FRIEZE}/database
    # Configure openarc to use this db instance

    ### Set up config directory
    cfg_directory = os.path.join(operating_directory, 'cfg')
    if not os.path.exists(cfg_directory):
        os.makedirs(cfg_directory, mode=0o700)
    os.chmod(cfg_directory, 0o700)

    ### Force openarc to use specified config
    openarc.env.initenv(cfgfile=os.path.join(cfg_directory, 'openarc.conf'), reset=True)

    cfg_file_path = os.path.join(cfg_directory, 'frieze.conf')
    print("Loading FRIEZE config: [%s]" % (cfg_file_path))
    try:
        with open(cfg_file_path) as f:
            appcfg = toml.loads(f.read())
            appcfg['runprops'] = { 'home' : operating_directory }
            openarc.env.getenv().merge_app_cfg('frieze', appcfg)

    except IOError:
        raise OAError("%s does not exist" % cfg_file_path)

    # Initialize the domain
    global p_domain
    gen_domain = False

    if p_domain:
        if domain==p_domain.domain:
            print(f"====> Session domain found")
            return p_domain
        else:
            gen_domain = True
    else:
        gen_domain = True

    if gen_domain:
        print(f"====> Generating new domain entry")
        try:
            p_domain = OAG_Domain(domain, 'by_domain')[-1]
            print(f"====> Found previously generated entry for [{domain}]")
        except OAGraphRetrieveError:
            print(f"====> Generating entry for [{domain}]")
            with OADbTransaction('Create domain: %s' % domain):
                p_domain =\
                    OAG_Domain().db.create({
                        'domain'       : domain,
                        'country'      : country if country else openarc.env.getenv('frieze').rootca.country,
                        'province'     : province if province else openarc.env.getenv('frieze').rootca.province,
                        'locality'     : locality if locality else openarc.env.getenv('frieze').rootca.locality,
                        'org'          : org,
                        'org_unit'     : org_unit if org_unit else openarc.env.getenv('frieze').rootca.organization_unit,
                        'contact'      : contact_email if contact_email else '%s@%s' % (openarc.env.getenv('frieze').rootca.contact_email, domain),
                        'version_name' : str(),
                        'deployed'     : False,
                    })

                # Assign a subnet
                p_domain.assign_subnet(SubnetType.SITE, hosts_expected=254)

                # Generate a certificate authority
                p_domain.trust().initialize()

    return p_domain
