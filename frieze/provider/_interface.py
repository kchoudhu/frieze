class CloudInterface(object):
    """Minimal functionality that needs to be implemented by a deriving shim
    to a cloud service"""
    def block_attach(self, blockstore):
        raise NotImplementedError("Implement in deriving Shim")

    def block_create(self, blockstore):
        raise NotImplementedError("Implement in deriving Shim")

    def block_detatch(self, blockstore):
        raise NotImplementedError("Implement in deriving Shim")

    def block_delete(self, subid):
        raise NotImplementedError("Implement in deriving Shim")

    def block_delete_mark(self, subid, label):
        raise NotImplementedError("Implement in deriving Shim")

    def block_list(self, show_delete=False):
        raise NotImplementedError("Implement in deriving Shim")

    def block_rootdisk(self):
        raise NotImplementedError("Implement in deriving Shim")

    def network_attach(self, host, network):
        raise NotImplementedError("Implement in deriving Shim")

    def network_create(self, site, label=None):
        raise NotImplementedError("Implement in deriving Shim")

    def network_iface_mtu(self, external=True):
        raise NotImplementedError("Implement in deriving Shim")

    def network_list(self, show_delete=False):
        raise NotImplementedError("Implement in deriving Shim")

    def server_create(self, host, networks=[], snapshot=None, label=None):
        raise NotImplementedError("Implement in deriving Shim")

    def server_delete_mark(self, server):
        raise NotImplementedError("Implement in deriving Shim")

    def server_list(self, show_delete=False):
        raise NotImplementedError("Implement in deriving Shim")

    def metadata_set_user_data(self, userdata):
        raise NotImplementedError("Implement in deriving Shim")

    def server_private_network_list(self):
        raise NotImplementedError("Implement in deriving Shim")

    def snapshot_list(self):
        raise NotImplementedError("Implement in deriving Shim")

    def sshkey_create(self, certauthority):
        raise NotImplementedError("Implement in deriving Shim")

    def sshkey_destroy(self, keyid):
        raise NotImplementedError("Implement in deriving Shim")

    def sshkey_list(self):
        raise NotImplementedError("Implement in deriving Shim")

