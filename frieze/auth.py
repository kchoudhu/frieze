#!/usr/bin/env python3

import enum
import os
import openarc.env
import openarc.exception
import datetime
import secrets
import string
import time

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from bless.config.bless_config import\
    BLESS_OPTIONS_SECTION,\
    CERTIFICATE_EXTENSIONS_OPTION,\
    REMOTE_USERNAMES_BLACKLIST_OPTION,\
    REMOTE_USERNAMES_VALIDATION_OPTION,\
    USERNAME_VALIDATION_OPTION,\
    BlessConfig
from bless.request.bless_request import\
    BlessSchema
from bless.ssh.certificate_authorities.ssh_certificate_authority_factory import \
    get_ssh_certificate_authority
from bless.ssh.certificates.ssh_certificate_builder import SSHCertificateType
from bless.ssh.certificates.ssh_certificate_builder_factory import get_ssh_certificate_builder
from marshmallow.exceptions import ValidationError

from openarc.oatime import OATime

class CertFormat(enum.Enum):
    SSH = 1
    PEM = 2

class CertAuth(object):
    def __init__(self, domain):

        self.domain = domain
        if not os.path.exists(self.root):
            os.makedirs(self.root, mode=0o700)
        os.chmod(self.root, 0o700)

        self.pw_file       = os.path.join(self.root, 'ca.pw')
        self.priv_key_file = os.path.join(self.root, 'ca.pem')
        self.pub_crt_file  = os.path.join(self.root, 'ca_pub.crt')
        self.pub_ssh_file  = os.path.join(self.root, 'ca_pub.ssh')

    def certificate(self, certformat=CertFormat.PEM):
        if certformat == CertFormat.PEM:
            with open(self.pub_crt_file, 'rb') as f:
                return f.read().decode()
        elif certformat == CertFormat.SSH:
            with open(self.pub_ssh_file, 'r') as f:
                return f.read()

    def distribute(self):
        from ._provider import ExtCloud

        # Publish our certificate authority
        for site in self.domain.site:
            extcloud = ExtCloud(site.provider)
            for key in extcloud.sshkey_list():
                extcloud.sshkey_destroy(key)
            extcloud.sshkey_create(self.name, self.certificate(certformat=CertFormat.SSH))
        return extcloud.sshkey_list()[0]

    def generate(self):

        # Generate a private key off the bat
        newca_priv_key =\
            rsa.generate_private_key(
                public_exponent=65537,
                key_size=4096,
                backend=default_backend(),
            )

        # What are we signing?
        newca_subject =\
            x509.Name([
                x509.NameAttribute(NameOID.COUNTRY_NAME, self.domain.country),
                x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, self.domain.province),
                x509.NameAttribute(NameOID.LOCALITY_NAME, self.domain.locality),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, self.domain.org),
                x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, self.domain.org_unit),
                x509.NameAttribute(NameOID.EMAIL_ADDRESS, self.domain.contact),
                x509.NameAttribute(NameOID.COMMON_NAME, "%s Certificate Authority" % self.domain.org),
            ])

        # Valid from
        newca_valid_from = OATime().now
        newca_valid_until = None

        # Use this to sign the key
        signing_key = None


        if self.is_intermediate_ca:

            signing_key = self.rootca_privkey

            # Validity is the lesser of ten years and validity of root
            newca_valid_until = newca_valid_from+datetime.timedelta(days=10*365.25)
            if newca_valid_until > self.rootca_cert.not_valid_after:
                newca_valid_until = self.rootca_cert.not_valid_after

            # In this case we're going to be singing a CSR
            csr =\
                x509.CertificateSigningRequestBuilder()\
                    .subject_name(newca_subject)\
                    .sign(newca_priv_key, hashes.SHA256(), default_backend())

            signable =\
                x509.CertificateBuilder()\
                    .subject_name(csr.subject)\
                    .issuer_name(self.rootca_cert.subject)\
                    .public_key(csr.public_key())\
                    .serial_number(x509.random_serial_number())\
                    .not_valid_before(newca_valid_from)\
                    .not_valid_after(newca_valid_until)
        else:

            # Self signed
            signing_key = newca_priv_key

            # validity is 10 years
            newca_valid_until = newca_valid_from+datetime.timedelta(days=10*365.25)

            signable =\
                x509.CertificateBuilder()\
                    .subject_name(newca_subject)\
                    .issuer_name(newca_subject)\
                    .public_key(newca_priv_key.public_key())\
                    .serial_number(x509.random_serial_number())\
                    .not_valid_before(newca_valid_from)\
                    .not_valid_after(newca_valid_until)

        cert = signable.sign(signing_key, hashes.SHA256(), default_backend())

        password=str().join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20)).encode()

        with open(os.open(self.priv_key_file, os.O_CREAT|os.O_WRONLY, 0o600), 'wb') as f:
            f.write(newca_priv_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=\
                    serialization.BestAvailableEncryption(password)
            ))
        with open(os.open(self.pub_crt_file, os.O_CREAT|os.O_WRONLY, 0o600), 'wb') as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        with open(os.open(self.pub_ssh_file, os.O_CREAT|os.O_WRONLY, 0o600), 'wb') as f:
            f.write(newca_priv_key.public_key().public_bytes(
                        encoding=serialization.Encoding.OpenSSH,
                        format=serialization.PublicFormat.OpenSSH
                    ))
        with open(os.open(self.pw_file, os.O_CREAT|os.O_WRONLY, 0o600), 'w') as f:
            f.write(password.decode())

        print("New certificate authority created for [%s]. Files:" % self.domain.org)
        print("   Private Key: [%s]" % self.priv_key_file)
        print("   Certificate: [%s]" % self.pub_crt_file)
        print("   Password:    [%s]" % self.pw_file)
        print("Certificate authority will remain valid until [%s]" % newca_valid_until)

    @property
    def is_intermediate_ca(self):
        try:
            setattr(self, '_rootca_private_key_file', os.path.expanduser(openarc.env.getenv().rootca['private_key']))
            setattr(self, '_rootca_certificate_file', os.path.expanduser(openarc.env.getenv().rootca['certificate']))
            setattr(self, '_rootca_password', openarc.env.getenv().rootca['password'].encode())
        except KeyError:
            setattr(self, '_rootca_private_key_file', str())
            setattr(self, '_rootca_certificate_file', str())
            setattr(self, '_rootca_password', str())

        return os.path.exists(self._rootca_private_key_file) and os.path.exists(self._rootca_certificate_file)

    @property
    def is_valid(self):
        """For now, just check the existence of these files to make sure that
        the CA looks to be in good shape"""
        if os.path.exists(self.root):
            if os.path.exists(self.pw_file)\
                and os.path.exists(self.priv_key_file)\
                and os.path.exists(self.pub_crt_file)\
                and os.path.exists(self.pub_ssh_file):
                return True
            else:
                return False
        else:
            return False

    def issue_ssh_certificate(self, user, command, remote_user='root', user_ip=None, validity_length=120, valid_src_ips=None, serialize_to_dir=None):

        ### Generate new key to be SSH signed
        user_private_key =\
            rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )

        ### Set up bless call
        config = BlessConfig(os.path.join(openarc.env.getenv().runprops['home'], 'cfg', 'bless.cfg'))
        schema = BlessSchema(strict=True)
        schema.context[USERNAME_VALIDATION_OPTION] =\
            config.get(BLESS_OPTIONS_SECTION, USERNAME_VALIDATION_OPTION)
        schema.context[REMOTE_USERNAMES_VALIDATION_OPTION] =\
            config.get(BLESS_OPTIONS_SECTION, REMOTE_USERNAMES_VALIDATION_OPTION)
        schema.context[REMOTE_USERNAMES_BLACKLIST_OPTION] =\
            config.get(BLESS_OPTIONS_SECTION, REMOTE_USERNAMES_BLACKLIST_OPTION)

        # Build up call
        event = {
            'bastion_user'       : user,
            'command'            : command,
            'public_key_to_sign' : user_private_key\
                                    .public_key()\
                                    .public_bytes(
                                        encoding=serialization.Encoding.OpenSSH,
                                        format=serialization.PublicFormat.OpenSSH
                                    ).decode(),
            'remote_usernames' : remote_user,
        }
        if user_ip:
            event['bastion_user_ip'] = user_ip
        if valid_src_ips:
            event['bastion_ips'] = valid_src_ips

        try:
            request =\
                schema.load(event).data
        except ValidationError as e:
            raise openarc.exception.OAError("Unable to validate schema for ssh key generation request")

        current_time = OATime().now
        valid_after  = int(OATime(current_time - datetime.timedelta(seconds=validity_length)).to_unixtime())
        valid_before = int(OATime(current_time + datetime.timedelta(seconds=validity_length)).to_unixtime())

        ca = get_ssh_certificate_authority(self.private_key, self.private_key_password)
        cert_builder = get_ssh_certificate_builder(ca, SSHCertificateType.USER,
                                                   request.public_key_to_sign)
        for username in request.remote_usernames.split(','):
            cert_builder.add_valid_principal(username)

        cert_builder.set_valid_before(valid_before)
        cert_builder.set_valid_after(valid_after)

        certificate_extensions = config.get(BLESS_OPTIONS_SECTION, CERTIFICATE_EXTENSIONS_OPTION)
        if certificate_extensions:
            for e in certificate_extensions.split(','):
                if e:
                    cert_builder.add_extension(e)
        else:
            cert_builder.clear_extensions()

        # cert_builder is needed to obtain the SSH public key's fingerprint
        kid_user = request.bastion_user
        if request.bastion_user_ip:
            kid_user += '@%s' % request.bastion_user_ip
        kid_command = request.command
        if request.bastion_ips:
            kid_command += ' from {%s}' % request.bastion_ips

        key_id = 'Issued for [{}] using ssh_key [{}] valid_to [{}] executing [{}]'.format(
            kid_user,
            cert_builder.ssh_public_key.fingerprint,
            time.strftime("%Y/%m/%d %H:%M:%S", time.gmtime(valid_before)),
            kid_command)
        if request.bastion_ips:
            cert_builder.set_critical_option_source_addresses(request.bastion_ips)
        cert_builder.set_key_id(key_id)
        cert = cert_builder.get_cert_file()

        # Return signed credential, or output it to a directory
        serialized_cert    = cert
        serialized_privkey = user_private_key.private_bytes(
                                 encoding=serialization.Encoding.PEM,
                                 format=serialization.PrivateFormat.PKCS8,
                                 encryption_algorithm=serialization.NoEncryption()
                             ).decode()

        if serialize_to_dir:
            if not os.path.exists(serialize_to_dir):
                os.makedirs(serialize_to_dir, mode=0o700)
            os.chmod(serialize_to_dir, 0o700)

            with open(os.open(os.path.join(serialize_to_dir, 'id_rsa.pub'), os.O_CREAT|os.O_WRONLY, 0o600), 'w') as f:
                f.write(serialized_cert)
            with open(os.open(os.path.join(serialize_to_dir, 'id_rsa'), os.O_CREAT|os.O_WRONLY, 0o600), 'w') as f:
                f.write(serialized_privkey)
        else:
            return (serialized_cert, serialized_privkey)

    @property
    def name(self):
        return "%s" % self.domain.domain

    @property
    def private_key_password(self):
        with open(self.pw_file, 'r') as f:
            return f.read().encode()

    @property
    def private_key(self):
        with open(self.priv_key_file, 'rb') as f:
            priv_key = f.read()
        return priv_key

    @property
    def root(self):
        return os.path.join(openarc.env.getenv().runprops['home'], 'domains', self.domain.domain, 'ca')

    @property
    def rootca_cert(self):
        if self.is_intermediate_ca:
            with open(self._rootca_certificate_file, 'rb') as f:
                rootca_cert =\
                    x509.load_pem_x509_certificate(f.read(), default_backend())
            return rootca_cert
        else:
            return None

    @property
    def rootca_password(self):
        if self.is_intermediate_ca:
            return self._rootca_password
        else:
            return None

    @property
    def rootca_privkey(self):
        if self.is_intermediate_ca:
            with open(self._rootca_private_key_file, 'rb') as f:
                rootca_key =\
                    serialization.load_pem_private_key(
                        f.read(),
                        password=self.rootca_password,
                        backend=default_backend()
                    )
            return rootca_key
        else:
            return None
