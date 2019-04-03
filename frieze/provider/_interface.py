class CloudInterface(object):
    """Minimal functionality that needs to be implemented by a deriving shim
    to a cloud service"""
    def block_attach(self, blockstore):
        raise NotImplementedError("No implementation yet")

    def block_create(self, blockstore):
        raise NotImplementedError("No implementation yet")

    def block_detatch(self, blockstore):
        raise NotImplementedError("No implementation yet")

    def block_delete(self, subid):
        raise NotImplementedError("No implementation yet")

    def block_delete_mark(self, subid, label):
        raise NotImplementedError("No implementation yet")

    def block_list(self, show_delete=False):
        raise NotImplementedError("No implementation yet")

    def block_rootdisk(self):
        raise NotImplementedError("No implementation yet")

    def dns_list_zones(self, name=None):
        raise NotImplementedError("No implementation yet")

    def dns_list_records(self, zone, types=[]):
        raise NotImplementedError("No implementation yet")

    def dns_upsert_record(self, vsubid, domain, alias, ip, ttl=60, type_='A'):
        raise NotImplementedError("No implementation yet")

    def network_attach(self, host, network):
        raise NotImplementedError("No implementation yet")

    def network_create(self, site, label=None):
        raise NotImplementedError("No implementation yet")

    def network_iface_mtu(self, external=True):
        raise NotImplementedError("No implementation yet")

    def network_list(self, show_delete=False):
        raise NotImplementedError("No implementation yet")

    def server_create(self, host, networks=[], snapshot=None, label=None):
        raise NotImplementedError("No implementation yet")

    def server_delete_mark(self, server):
        raise NotImplementedError("No implementation yet")

    def server_list(self, show_delete=False):
        raise NotImplementedError("No implementation yet")

    def metadata_set_user_data(self, userdata):
        raise NotImplementedError("No implementation yet")

    def server_private_network_list(self):
        raise NotImplementedError("No implementation yet")

    def snapshot_list(self):
        raise NotImplementedError("No implementation yet")

    def sshkey_create(self, certauthority):
        raise NotImplementedError("No implementation yet")

    def sshkey_destroy(self, keyid):
        raise NotImplementedError("No implementation yet")

    def sshkey_list(self):
        raise NotImplementedError("No implementation yet")
