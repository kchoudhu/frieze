#!/usr/bin/env python3

import dateutil.relativedelta
import unittest
import sys

sys.path.append('../..')

import frieze

from testhelper          import *

from openarc             import *
from openarc.env         import gctx
from openarc.dao         import OADao
from openarc.exception   import OAError

class TestSubscriptions(unittest.TestCase, TestBase):
    def setUp(self):
        self.setUp_db()
        pass

    def tearDown(self):
        # self.tearDown_db()
        pass

    def __show_domain_state(self, domain):
        formatstr = "%-10s|%-20s|%-10s|%-10s|%-10s|%-15s|%-15s|%-15s"
        for site in domain.site:
            print("="*111)
            print("Site: %s (%s)" % (site.name, site.shortname))

            for host in site.host:
                print('\n> %s\n' % host.fqdn)
                print(formatstr % ('iface', 'routingstyle', 'bird', 'dhcpd', 'isgw', 'ip4', 'gw', 'bcast'))
                print('-'*111)
                for iface in host.net_iface:
                    print(formatstr % (
                        iface.name,
                        iface.routingstyle,
                        iface.bird_enabled,
                        iface.dhcpd_enabled,
                        iface.is_gateway,
                        iface.ip4,
                        iface.gateway,
                        iface.broadcast))
                print('-'*111)

    def test_frieze_highlevel_api(self):

        domain = frieze.set_domain('anserinae.net')

        site = domain.add_site('New York Equinix Contract 1', 'ny1')

        # Create host template
        host_template =\
            frieze.HostTemplate(**{
                'cpus'       : 1,
                'memory'     : 1024,
                'bandwidth'  : 1024,
                'provider'   : frieze.Host.Provider.DIGITALOCEAN,
                'interfaces' : [
                    # Iface-----ext(t)/int(f)
                    ('vtnet0',  True),
                    ('vtnet1',  False),
                ],
                'sysctls' : [
                    # Tunable--------------------------------boot----value
                    (frieze.Tunable.F_HW_VTNET_CSUM_DISABLE, True,   "1"), # Do not checksum on VTNET interfaces
                    (frieze.Tunable.F_NET_FIBS,              True,   "2")  # We need two routing tables (one for internal, one for external)
                ]
            })

        # Add 2 compute hosts. Right now, both of these hosts are default
        # externally routed, EVEN if they have more than one network interface
        for i, hostname in enumerate(['particularjustice', 'ascendantjustice']):
            host = site.add_host(**{
                'template'  : host_template,
                'name'      : hostname,
                'role'      : frieze.Host.Role.COMPUTE
            })

        # No sitebastion yet
        try:
            site.bastion
        except OAError:
            pass

        # Adding a sitebastion initiates a routing setup that routes all external
        # compute host traffic through the sitebastion (i.e. the sitebastion
        # becomes the default gateway). The hosts still remain accessible through
        # internet, but ONLY via SSH, and ONLY on fib 1. Additionally, the
        # external facing interface
        sitebastion = site.add_host(**{
            'template'  : host_template,
            'name'      : 'installation01',
            'role'      : frieze.Host.Role.SITEBASTION
        })

        host = site.add_host(**{
            'template'  : host_template,
            'name'      : 'regnaljustice',
            'role'      : frieze.Host.Role.COMPUTE
        })

        site = domain.add_site('New York Equinix Contract 2', 'ny2')

        # Add 2 compute hosts. Right now, both of these hosts are default
        # externally routed, EVEN if they have more than one network interface
        for i, hostname in enumerate(['particularjustice', 'ascendantjustice']):
            host = site.add_host(**{
                'template'  : host_template,
                'name'      : hostname,
                'role'      : frieze.Host.Role.COMPUTE
            })

        # No sitebastion yet
        try:
            site.bastion
        except OAError:
            pass

        # Adding a sitebastion initiates a routing setup that routes all external
        # compute host traffic through the sitebastion (i.e. the sitebastion
        # becomes the default gateway). The hosts still remain accessible through
        # internet, but ONLY via SSH, and ONLY on fib 1. Additionally, the
        # external facing interface
        sitebastion = site.add_host(**{
            'template'  : host_template,
            'name'      : 'installation01',
            'role'      : frieze.Host.Role.SITEBASTION
        })

        host = site.add_host(**{
            'template'  : host_template,
            'name'      : 'regnaljustice',
            'role'      : frieze.Host.Role.COMPUTE
        })

        # Like other templates, we would expect to define this in a config.
        # But hey, frieze is configuration for *programmers*. Let's define a
        # few services and cobble them together
        openrelayd_template =\
            frieze.AppTemplate(name="openrelay_restd")

        msqlsd_template =\
            frieze.AppTemplate(name="mysqld")

        nextcloud_tempalte =\
            frieze.AppTemplate(name="nextcloud")

        # Define a deployment to hold our applications, and define where it runs
        # by adding it to the site.
        #
        # Deployments run on a separate VLAN, and can span multiple sites.
        # Sitebastions therefore have to be aware of all possible vlans. The
        # call to add_deployment adds these vlans across the board
        infra_depl = domain.add_deployment("infra", affinity=site)

        openrelay_depl = domain.add_deployment("openrelay", affinity=site)

        # Deployments run applications inside containers. Use the "stripes" param
        # to specify how many containers to use; one stripe = one instance of
        # the application running in a container
        #
        # The affinity parameter defines what site you want to run these app
        # stripes on. It is binding: if there are more stripes than slots for
        # them on compute hosts on the site, the overflowing stripes won't run
        infra_depl.add_application(openrelayd_template, affinity=site, stripes=4)

        # Application stripes without an affinity are deployed on whatever compute
        # hosts are available. If slots run out, the overflowing stripes won't run
        infra_depl.add_application(openrelayd_template, stripes=4)

        # An application without stripes will default to initializing one stripe.
        infra_depl.add_application(msqlsd_template)

        print('domain:', domain.containers.size)
        print('site:',   site.containers.size)
        print('host:',   host.containers.size)

        # Some exposition
        print(host.os)
        for tunable in host.sysctls:
            print(tunable.tunable, tunable.value)

        # domain.configure()

    class SQL(TestBase.SQL):
        pass

if __name__ == '__main__':
    unittest.main()
