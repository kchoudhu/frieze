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

def _generate_ca(domain, ca_dir, ca_pw_file, ca_priv_key_file, ca_pub_crt_file, ca_pub_ssh_file):

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
            x509.NameAttribute(NameOID.COUNTRY_NAME, domain.country),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, domain.province),
            x509.NameAttribute(NameOID.LOCALITY_NAME, domain.locality),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, domain.org),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, domain.org_unit),
            x509.NameAttribute(NameOID.EMAIL_ADDRESS, domain.contact),
            x509.NameAttribute(NameOID.COMMON_NAME, "%s Certificate Authority" % domain.org),
        ])

    # Valid from
    newca_valid_from = OATime().now
    newca_valid_until = None

    # Use this to sign the key
    signing_key = None

    try:
        rootca_private_key_file = os.path.expanduser(openarc.env.getenv().rootca['private_key'])
        rootca_certificate_file = os.path.expanduser(openarc.env.getenv().rootca['certificate'])
    except KeyError:
        rootca_private_key_file = str()
        rootca_certificate_file = str()
    if os.path.exists(rootca_private_key_file) and os.path.exists(rootca_certificate_file):

        # User root CA to sign
        with open(rootca_private_key_file, 'rb') as f:
            rootca_key =\
                serialization.load_pem_private_key(
                    f.read(),
                    password=openarc.env.getenv().rootca['password'].encode(),
                    backend=default_backend()
                )
        with open(rootca_certificate_file, 'rb') as f:
            rootca_cert =\
                x509.load_pem_x509_certificate(f.read(), default_backend())

        signing_key = rootca_key

        # Validity is the lesser of ten years and validity of root
        newca_valid_until = newca_valid_from+datetime.timedelta(days=10*365.25)
        if newca_valid_until > rootca_cert.not_valid_after:
            newca_valid_until = rootca_cert.not_valid_after

        # In this case we're going to be singing a CSR
        csr =\
            x509.CertificateSigningRequestBuilder()\
                .subject_name(newca_subject)\
                .sign(newca_priv_key, hashes.SHA256(), default_backend())

        signable =\
            x509.CertificateBuilder()\
                .subject_name(csr.subject)\
                .issuer_name(rootca_cert.subject)\
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

    if not os.path.exists(ca_dir):
        os.makedirs(ca_dir, mode=0o700)
    os.chmod(ca_dir, 0o700)

    with open(os.open(ca_priv_key_file, os.O_CREAT|os.O_WRONLY, 0o600), 'wb') as f:
        f.write(newca_priv_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=\
                serialization.BestAvailableEncryption(password)
        ))
    with open(os.open(ca_pub_crt_file, os.O_CREAT|os.O_WRONLY, 0o600), 'wb') as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(os.open(ca_pub_ssh_file, os.O_CREAT|os.O_WRONLY, 0o600), 'wb') as f:
        f.write(newca_priv_key.public_key().public_bytes(
                    encoding=serialization.Encoding.OpenSSH,
                    format=serialization.PublicFormat.OpenSSH
                ))
    with open(os.open(ca_pw_file, os.O_CREAT|os.O_WRONLY, 0o600), 'w') as f:
        f.write(password.decode())

    print("New certificate authority created for [%s]. Files:" % domain.org)
    print("   Private Key: [%s]" % ca_priv_key_file)
    print("   Certificate: [%s]" % ca_pub_crt_file)
    print("   Password:    [%s]" % ca_pw_file)
    print("Certificate will remain valid until [%s]" % newca_valid_until)


def generate_certificate_authority(domain, op_dir):

    # Does it already exist?
    ca_dir = os.path.join(openarc.env.getenv().runprops['home'], 'domains', domain.domain, 'ca')

    ca_pw_file       = os.path.join(ca_dir, 'ca.pw')
    ca_priv_key_file = os.path.join(ca_dir, 'ca.pem')
    ca_pub_crt_file  = os.path.join(ca_dir, 'ca_pub.crt')
    ca_pub_ssh_file  = os.path.join(ca_dir, 'ca_pub.ssh')

    if os.path.exists(ca_dir):
        if os.path.exists(ca_pw_file)\
            and os.path.exists(ca_priv_key_file)\
            and os.path.exists(ca_pub_crt_file)\
            and os.path.exists(ca_pub_ssh_file):
            print("Using existing certificate authority in [%s]" % ca_dir)
        else:
            _generate_ca(domain, ca_dir, ca_pw_file, ca_priv_key_file, ca_pub_crt_file, ca_pub_ssh_file)
    else:
        _generate_ca(domain, ca_dir, ca_pw_file, ca_priv_key_file, ca_pub_crt_file, ca_pub_ssh_file)
