#!/usr/bin/env python3

import os
import openarc.env
import datetime
import secrets
import string

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from openarc.oatime import OATime

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

    @property
    def root(self):
        return os.path.join(openarc.env.getenv().runprops['home'], 'domains', self.domain.domain, 'ca')
