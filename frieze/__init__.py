#!/usr/bin/env python3

import importlib
import os
import openarc
import toml

from . import _core

from ._core import *

# Set up operating environment

### Does the operating directory exist?
operating_directory = os.path.expanduser('~/.frieze')
if not os.path.exists(operating_directory):
    os.makedirs(operating_directory, mode=0o700)
os.chmod(operating_directory, 0o700)

### Set up the database directory
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
openarc.oainit(cfgfile=os.path.join(cfg_directory, 'openarc.conf'), reset=True)
importlib.reload(openarc)

cfg_file_path = os.path.join(cfg_directory, 'frieze.conf')
print("Loading FRIEZE config: [%s]" % (cfg_file_path))
try:
    with open(cfg_file_path) as f:
        appcfg = toml.loads(f.read())
        appcfg['runprops'] = { 'home' : operating_directory }
        openarc.oaenv.merge_app_cfg('frieze', appcfg)
except IOError:
    raise OAError("%s does not exist" % cfg_file_path)

__all__ = []
__all__.extend(_core.__all__)


del(os)
del(openarc)
del(toml)
