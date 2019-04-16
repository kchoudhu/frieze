#!/usr/bin/env python3

import sys
import unittest
sys.path.append('../..')
from testhelper import *

# Monkeypatch capabilities and then make them available
import frieze
frieze.capability.add('~/run/dist/frieze')
import frieze.capability
import frieze.hosttype

class TestSubscriptions(unittest.TestCase, TestBase):
    def setUp(self):
        self.setUp_db()
        pass

    def tearDown(self):
        # self.tearDown_db()
        pass

    def __show_domain_state(self, domain):

        print("Domain: %s" % domain.domain)
        print("  Sites:      %d" % domain.site.size)
        print("  Containers: %d" % domain.containers.size)

        for site in domain.site:
            print("Site: %s (%s)" % (site.name, site.shortname))
            print('Network Stats')
            print(frieze.Netif.formatstr % ('iface', 'routingstyle', 'fib', 'bird', 'dhcpd', 'isgw', 'ip4', 'gw', 'bcast'))
            print('   ', '-'*111)
            for host in site.host:

                print('  %s' % host.fqdn)
                for iface in host.net_iface:
                    iface.summarize()
            print('   ', '-'*111)

            print('Host Tunable')
            for host in site.host:
                print('  %s:' % host.fqdn)
                for tunable in host.sysctl:
                    print('    %s %s' % (tunable.tunable, tunable.value))

            print('Storage Stats')
            print('  Block Devices Created: %d' % site.block_storage.size)
            if site.block_storage.size > 0:
                for block_storage in site.block_storage:
                    print('   ', block_storage.blockstore_name)
            print('  Host ZFS Mounts')
            for host in site.compute_hosts:
                zpool = str()
                print('   ', host.fqdn)
                if host.block_storage.size>0:
                    for block_storage in host.block_storage:
                        if zpool != block_storage.zpool:
                            print('     ', block_storage.zpool)
                            zpool = block_storage.zpool
                        print('       ', block_storage.dataset, '->', block_storage.mount_point)

            print('Container Stats')
            for host in site.host:
                print(' %s' % host.fqdn)
                for container in host.containers:
                    print('   %s: %d %s' % (container.fqdn, container.block_storage.size, container.ip4()))

            # print('Container ZFS datasets')
            # for container in site.containers:
            #     cur_container = str()
            #     print('  %s' % container.fqdn)
            #     for block_storage in container.block_storage:
            #         if container.fqdn != cur_container:
            #             cur_container = container.fqdn
            #         print('    %s' % block_storage.dataset)

    def test_frieze_qa_env(self):


        def init(snapcount):

            # Create host template
            class SmallCompute(frieze.hosttype.HostTemplate):
                cores     = 1
                memory    = 1024
                bandwidth = 1024
                os        = frieze.osinfo.HostOS.FreeBSD_12_0

            print(f"===> Set domain")
            domain = frieze.set_domain('openrelay.io', 'OpenRelay')

            print(f"===> Adding site")
            site =\
                domain.add_site(
                    'Vultr NY1', 'ny1',
                    frieze.provider.CloudProvider.VULTR,
                    frieze.provider.Location.NY
                )

            print("===> Add bastion host")
            sitebastion = site.add_host(**{
                'template'  :  SmallCompute,
                'name'      : 'installation01',
                'role'      :  frieze.HostRole.SITEBASTION
            })

            # Add compute
            print("===> Add compute hosts")
            for i, hostname in enumerate(['particularjustice', 'ascendantjustice']):
                host = site.add_host(**{
                    'template'  : SmallCompute,
                    'name'      : hostname,
                    'role'      : frieze.HostRole.COMPUTE
                })

            print("===> Add deployment: infra")
            infra_depl = domain.add_deployment("infra", affinity=site)


            # Capabilities can be added to deployments using a chain of add_capability calls.
            #
            # stripes:        number of stripes of the capability need to be added.
            # max_stripes:    number of stripes of the capability the deployment can hold. If
            #                 specified, can override stripes parameter.
            # expose:         capability can be accessed via egress site bastion. If there is
            #                 more than one stripe, sitebastion will loadbalance between all known
            #                 stripes
            # external_alias: required if expose parameter is set, list of domain aliases to be
            #                 set in external DNS manager
            print("===> Add deployment capabilities")
            infra_depl\
                .add_capability(
                    frieze.capability.openrelay(),
                    max_stripes=1,
                    custom_pkg=True
                ).add_capability(
                    frieze.capability.postgres(),
                    max_stripes=1
                ).add_capability(
                    frieze.capability.nginx(),
                    stripes=2,
                    max_stripes=2,
                    expose=site,
                    secure=True,
                    external_alias=['', 'www']
                )

            print("===> Add deployment: app")
            app_depl = domain.add_deployment("app", affinity=site)

            print("===> Add deployment capabilities")
            app_depl.add_capability(frieze.capability.nginx(), stripes=1, max_stripes=2)

            print("===> Snapshot domain")
            snap = domain.snapshot(f"QA deployment {snapcount}")

            print("===> Deploy snapshot")
            snap.deploy(push=True)

            return site

        for snapcount in range(1):
            if snapcount>0:
                domain = site.txnclone().root_domain
            site = init(snapcount)
            print("======>")

    class SQL(TestBase.SQL):
        pass

if __name__ == '__main__':
    unittest.main()
