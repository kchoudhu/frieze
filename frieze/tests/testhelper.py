#!/usr/bin/env python3

import base64
import psycopg2
import psycopg2.extras
import openarc
import os
import sys

sys.path.append('../..')

from textwrap    import dedent as td

class TestBase(object):
    """Mixin class to assist with database testing"""
    def check_autonode_equivalence(self, oag1, oag2):
        for oagkey in oag1.streams.keys():
            if oag1.is_oagnode(oagkey):
                self.assertEqual(getattr(oag1, oagkey, "").id, getattr(oag2, oagkey, "").id)
            else:
                self.assertEqual(getattr(oag1, oagkey, ""), getattr(oag2, oagkey, ""))

    def __kill_schemata(self):
        with self.dbconn.cursor() as cur:
            for schema in ['frieze']:
                cur.execute(self.SQL.drop_test_schema % (schema))
            self.dbconn.commit()

    def setUp_db(self):
        openarc.env.initenv(on_demand_oags=True)
        self.dbconn = psycopg2.connect(**openarc.env.getenv().dbinfo)
        self.__kill_schemata()

    def tearDown_db(self):
        self.__kill_schemata()
        self.dbconn.close()

    class SQL(object):
        ## Test schema helper SQL
        drop_test_schema = td("""
            DROP SCHEMA IF EXISTS %s CASCADE""")
