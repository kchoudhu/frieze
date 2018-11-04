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

    def test_frieze_highlevel_api(self):

        gctx().logger.SQL = True

        domain = frieze.set_domain('anserinae.net')

        site = domain.add_site('New York Equinix Contract 1', 'ny1')

        # The average host is
        host = site.add_host(**{
            'cpus'      : 1,
            'memory'    : 1024,
            'bandwidth' : 1024,
            'provider'  : frieze.Host.Provider.DIGITALOCEAN,
            'name'      : 'installation01',
            'role'      : frieze.Host.Role.SITEBASTION
        })

    class SQL(TestBase.SQL):
        pass

if __name__ == '__main__':
    unittest.main()
