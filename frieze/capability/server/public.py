__all__ = [
    'TrustType',
    'CertAction',
    'CertAuthInternal',
    'CertAuthLetsEncrypt',
    'CertFormat',
    'ExtDNS'
]

import acme.challenges, acme.client, acme.errors, acme.messages, acme.crypto_util
import base64
import datetime
import enum
import hashlib
import josepy
import json
import openarc.env
import openarc.exception
import os
import pprint
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

from frieze.provider import ExtCloud

class CertFormat(enum.Enum):
    SSH = 1
    PEM = 2

class CertAction(enum.Enum):
    HOST_ACCESS_USER = 'user host access'
    HOST_ACCESS_AUTO = 'auto host access'
    REMOTE_ACCESS    = 'secure remote access'
    IDENTITY         = 'identity'

    def desc(self, info=None):
        return f'{self.value}: {info}' if info else f'{self.value}'

class TrustType(enum.Enum):
    INTERNAL    = 'internal'
    LETSENCRYPT = 'letsencrypt'

class Certificate(object):
    def __init__(self, authority, subjects):
        self.authority = authority
        self.primary_subject = None
        self.subjects  = []
        for subject in subjects:
            ns_subject = subject.strip()
            if not self.primary_subject:
                self.primary_subject = ns_subject
            self.subjects.append(ns_subject)
            self.subjects.sort()
        self.csr = None

    @property
    def chain(self):
        """Return a pyca/cryptography object representing an issued certificate"""
        try:
            with open(self.files['chain'], 'rb') as f:
                return f.read().decode('utf-8')
        except:
            return None

    def create_csr(self, random_alt_subject=False, force=False):
        """Use pyca/cryptography to create CSR object"""
        if not force and self.is_valid:
            print("This certificate is already issued and valid, not issuing CSR")
            return

        subject_key =\
            rsa.generate_private_key(
                public_exponent=65537,
                key_size=openarc.env.getenv('frieze').acme['keylen'],
                backend=default_backend(),
            )

        subject_key_pem =\
            subject_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            )

        # Use pyca/cryptography to generate csr
        subjects = list(self.subjects)
        if random_alt_subject:
            random_domain = base64.b16encode(os.urandom(5)).decode('utf-8')
            random_domain = f'{random_domain}.{self.authority.domain.domain}'.lower()
            subjects.append(random_domain)

        csr =\
            x509.CertificateSigningRequestBuilder(
            ).subject_name(
                x509.Name([
                    x509.NameAttribute(NameOID.COMMON_NAME, self.primary_subject),
                ])
            ).add_extension(
                x509.SubjectAlternativeName(
                    [x509.DNSName(subject) for subject in subjects]
                ),
                critical=False,
            ).sign(subject_key, hashes.SHA256(), default_backend())

        if not os.path.exists(self.path()):
            os.makedirs(self.path(), mode=0o700)
        os.chmod(self.path(), 0o700)

        with open(os.open(self.files['private'], os.O_CREAT|os.O_WRONLY, 0o600), 'wb') as f:
            f.write(subject_key_pem)

        return (csr.public_bytes(serialization.Encoding.PEM), subjects)

    @property
    def files(self):
        return {
            'chain'   : os.path.join(self.path(), 'chain.crt'),
            'private' : os.path.join(self.path(), 'private.pem'),
        }

    @property
    def inferred_name(self):
        return hashlib.sha256(','.join(self.subjects).encode('utf-8')).hexdigest()

    @property
    def is_valid(self):
        # Do the path validation thing
        return (
            os.path.exists(self.files['chain'])
            and os.path.exists(self.files['private'])
        )

    def path(self, rootdir=None):
        # The same certificate *may* map to multiple aliases. We need a way to reproducibly
        # go from aliases -> on-disk directory.
        if not rootdir:
            rootdir = self.authority.certdir
        return os.path.join(rootdir, self.inferred_name)

    @property
    def private_key(self):
        """Return bytes of the private key used to sign the certificate"""
        try:
            with open(self.files['private'], 'rb') as f:
                return f.read().decode('utf-8')
        except:
            return None

class CertAuthBase(object):
    def __init__(self, domain):
        self.domain = domain
        if not os.path.exists(self.root):
            os.makedirs(self.root, mode=0o700)
        os.chmod(self.root, 0o700)

    def issue_certificate(self, *args, cert_format=CertFormat.SSH, **kwargs):
        """By default, return SSH formatted certificates."""
        return {
            CertFormat.SSH : self._issue_ssh_certificate,
            CertFormat.PEM : self._issue_pem_certificate,
        }[cert_format](*args, **kwargs)

    @property
    def certdir(self):
        return os.path.join(self.root, 'certs')

    @property
    def root(self):
        return os.path.join(openarc.env.getenv('frieze').runprops.home, 'domains', self.domain.domain, 'trust', self.trust_type.value)

class CertAuthLetsEncrypt(CertAuthBase):

    trust_type = TrustType.LETSENCRYPT

    def __init__(self, domain):
        super().__init__(domain)
        self.acme_account_key_file  = os.path.join(self.root, 'account.jwk')
        self.acme_registration_file = os.path.join(self.root, 'registration.jwk')

        from ...provider import CloudProvider
        self.dns_provider = CloudProvider[openarc.env.getenv('frieze').extdns['provider'].upper()]

    @property
    def is_valid(self):
        return os.path.exists(self.acme_account_key_file)

    def __challenge_select(self, orderr, type_=acme.challenges.DNS01):
        """Loop through available challenges and return the one that matches
        type_ in dict (not json) form."""
        cbodies = {}
        authz_list = orderr.authorizations
        for authz in authz_list:
            cbodies[authz.body.identifier.value] = {}
            for i in authz.body.challenges:
                # Find the supported challenge.
                if isinstance(i.chall, type_):
                    response, validation = i.chall.response_and_validation(self.acme_client.net.key)
                    cbodies[authz.body.identifier.value] = {
                        'chall'      : i,
                        'response'   : response,
                        'validation' : validation
                    }

        return cbodies

    def _issue_pem_certificate(self, subject, command, remote_user='root', user_ip=None, validity_length=120, valid_src_ips=None, serialize_to_dir=None):

        if type(subject)!=list:
            subject = [subject]

        cert = Certificate(self, subject)
        if cert.is_valid:
            print(f"Valid certificate found for {subject}, not re-issuing")
        else:
            random_alt_subject = False
            try:
                (csr, csr_subjects) = cert.create_csr()
                orderr = self.acme_client.new_order(csr)
            except acme.messages.Error as e:
                # work around rate limits...
                print(e)
                (csr, csr_subjects) = cert.create_csr(random_alt_subject=True)
                orderr = self.acme_client.new_order(csr)

            cbodies = self.__challenge_select(orderr)

            # Create DNS txt record
            extcloud = ExtCloud(self.dns_provider)
            extzone = extcloud.dns_list_zones(name=self.domain.domain)[0]
            for subject, cbody in cbodies.items():
                print(f"[{subject}] Creating DNS validation TXT [{cbody['validation']}]")
                zone = extcloud.dns_upsert_record(extzone['vsubid'], f'_acme-challenge.{subject}', cbody['validation'], ttl=5, type_='TXT')
            del(extcloud)

            print(f"Waiting 60 seconds for DNS propagation")
            time.sleep(60)

            def loop_verification(trycount):
                acme_client = self.acme_client
                print(f'[try {trycount}] Answering challenges')
                for subject, cbody in cbodies.items():
                    print(f'  Processing: {subject}')
                    acme_client.answer_challenge(cbody['chall'], cbody['response'])

                print(f'Finalizing certificate')
                finalized_orderr = acme_client.poll_and_finalize(orderr)

                print(f'Writing out to disk')
                with open(os.open(cert.files['chain'], os.O_CREAT|os.O_WRONLY, 0o600), 'wb') as f:
                    f.write(finalized_orderr.fullchain_pem.encode())

            try:
                loop_verification(1)
            except acme.errors.TimeoutError:
                loop_verification(2)

        return cert

    def _issue_ssh_certificate(self, subject, command, remote_user='root', user_ip=None, validity_length=120, valid_src_ips=None, serialize_to_dir=None):
        raise OAError(f"You can't issue SSH certificates with [{self.trust_type.value} authority")

    def __get_acme_client(self, key):

        clargs = {
            'account' : self.acme_registration,
            'user_agent' : openarc.env.getenv('frieze').acme['useragent']
        }

        net = acme.client.ClientNetwork(key, **clargs)
        directory =\
            acme.messages.Directory.from_json(
                net.get(self.acme_url).json()
            )
        return acme.client.ClientV2(directory, net=net)

    @property
    def acme_account_key(self):
        """Return a fully validated ACME account credential in JWK format. If not found on
        disk, create and validate one with the ACME authority"""
        if not self.is_valid:
            print(f"Creating account for [{self.trust_type.value}]")
            account_privkey =\
                josepy.JWKRSA(key=rsa.generate_private_key(
                    public_exponent=65537,
                    key_size=2048,
                    backend=default_backend(),
                ))

            acme_client = self.__get_acme_client(account_privkey)
            regr = acme_client.new_account(
                acme.messages.NewRegistration.from_data(
                    email=self.domain.contact,
                    terms_of_service_agreed=True,
                )
            )

            # Write registration file
            with open(os.open(self.acme_registration_file, os.O_CREAT|os.O_WRONLY, 0o600), 'w') as f:
                f.write(regr.json_dumps())

            # And store the key in JWK form
            with open(os.open(self.acme_account_key_file, os.O_CREAT|os.O_WRONLY, 0o600), 'w') as f:
                f.write(account_privkey.json_dumps())

        with open(self.acme_account_key_file, 'r') as f:
            account_privkey = josepy.JWKRSA.json_loads(f.read())

        return account_privkey

    @property
    def acme_registration(self):
        try:
            with open(self.acme_registration_file, 'r') as f:
                return acme.messages.RegistrationResource.json_loads(f.read())
        except:
            return None

    @property
    def acme_client(self):
        return self.__get_acme_client(self.acme_account_key)

    @property
    def acme_url(self):
        return {
            'prod'    : 'https://acme-v02.api.letsencrypt.org/directory',
            'staging' : 'https://acme-staging-v02.api.letsencrypt.org/directory'
        }[openarc.env.getenv('frieze').acme['env']]

    @property
    def root(self):
        return os.path.join(super().root, openarc.env.getenv('frieze').acme['env'])

class CertAuthInternal(CertAuthBase):

    trust_type = TrustType.INTERNAL

    def __init__(self, domain):

        super().__init__(domain)

        self.pw_file       = os.path.join(self.root, 'ca.pw')
        self.priv_key_file = os.path.join(self.root, 'ca.pem')
        self.pub_crt_file  = os.path.join(self.root, 'ca_pub.crt')
        self.pub_ssh_file  = os.path.join(self.root, 'ca_pub.ssh')

    @property
    def certificate_rootdir(self):
        return os.path.join(self.trust_rootdir, 'certs')

    def certificate(self, certformat=CertFormat.PEM):
        if certformat == CertFormat.PEM:
            with open(self.pub_crt_file, 'rb') as f:
                return f.read().decode()
        elif certformat == CertFormat.SSH:
            with open(self.pub_ssh_file, 'r') as f:
                return f.read()

    def distribute_authority(self):
        # Publish our certificate authority in SSH form.
        for site in self.domain.site:
            extcloud = ExtCloud(site.provider)
            for key in extcloud.sshkey_list():
                extcloud.sshkey_destroy(key)
            extcloud.sshkey_create(self.domain.domain, self.certificate(certformat=CertFormat.SSH))
        return extcloud.sshkey_list()[0]

    def initialize(self):

        # Not bothering with refreshing
        if self.is_valid:
            print(f"Not refreshing backend trust [{self.trust_type.value}]")
            return

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
            setattr(self, '_rootca_private_key_file', os.path.expanduser(openarc.env.getenv('frieze').rootca.private_key))
            setattr(self, '_rootca_certificate_file', os.path.expanduser(openarc.env.getenv('frieze').rootca.certificate))
            setattr(self, '_rootca_password', openarc.env.getenv('frieze').rootca.password.encode())
        except KeyError:
            setattr(self, '_rootca_private_key_file', str())
            setattr(self, '_rootca_certificate_file', str())
            setattr(self, '_rootca_password', str())

        return os.path.exists(self._rootca_private_key_file) and os.path.exists(self._rootca_certificate_file)

    @property
    def is_valid(self):
        """For now, just check the existence of these files to make sure that
        the CA looks to be in good shape"""
        return (
            os.path.exists(self.pw_file)
            and os.path.exists(self.priv_key_file)
            and os.path.exists(self.pub_crt_file)
            and os.path.exists(self.pub_ssh_file)
        )

    def _issue_pem_certificate(self, subject, command, remote_user='root', user_ip=None, validity_length=120, valid_src_ips=None, serialize_to_dir=None):
        raise NotImplementedError("No implementation yet")

    def _issue_ssh_certificate(self, subject, command, remote_user='root', user_ip=None, validity_length=300, valid_src_ips=None, serialize_to_dir=None):

        ### Generate new key to be SSH signed
        subject_private_key =\
            rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )

        ### Set up bless call
        config = BlessConfig(os.path.join(openarc.env.getenv('frieze').runprops.home, 'cfg', 'bless.cfg'))
        schema = BlessSchema(strict=True)
        schema.context[USERNAME_VALIDATION_OPTION] =\
            config.get(BLESS_OPTIONS_SECTION, USERNAME_VALIDATION_OPTION)
        schema.context[REMOTE_USERNAMES_VALIDATION_OPTION] =\
            config.get(BLESS_OPTIONS_SECTION, REMOTE_USERNAMES_VALIDATION_OPTION)
        schema.context[REMOTE_USERNAMES_BLACKLIST_OPTION] =\
            config.get(BLESS_OPTIONS_SECTION, REMOTE_USERNAMES_BLACKLIST_OPTION)

        # Build up call
        event = {
            'bastion_user'       : subject,
            'command'            : command,
            'public_key_to_sign' : subject_private_key\
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
            print(e)
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
        serialized_privkey = subject_private_key.private_bytes(
                                 encoding=serialization.Encoding.PEM,
                                 format=serialization.PrivateFormat.PKCS8,
                                 encryption_algorithm=serialization.NoEncryption()
                             ).decode()

        if serialize_to_dir:
            serialize_to_dir = os.path.expanduser(serialize_to_dir)

            if not os.path.exists(serialize_to_dir):
                os.makedirs(serialize_to_dir, mode=0o700)
            os.chmod(serialize_to_dir, 0o700)

            id_name     = 'id_rsa_%s' % self.domain.domain
            id_file     = os.path.join(serialize_to_dir, id_name)
            id_file_pub = os.path.join(serialize_to_dir, '%s.pub' % id_name)
            with open(os.open(id_file, os.O_CREAT|os.O_WRONLY, 0o600), 'w') as f:
                f.write(serialized_privkey)
            with open(os.open(id_file_pub, os.O_CREAT|os.O_WRONLY, 0o600), 'w') as f:
                f.write(serialized_cert)
            return (id_file, id_file_pub)
        else:
            return (serialized_cert, serialized_privkey)

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

class ExtDNS(object):

    def __init__(self, domain):
        from ...provider import CloudProvider
        self.domain = domain
        self.provider = CloudProvider[openarc.env.getenv('frieze').extdns['provider'].upper()]

    def distribute(self):
        from ..._core import FIB

        # Generate list of aliases that need to be created
        needed = {}
        for site in self.domain.site:
            bastion_ip = site.bastion.ip4(fib=FIB.WORLD)
            for cap in site.capability_expose:
                for ca in cap.capability_alias:
                    needed[ca.fqdn] = bastion_ip

        # Initialize provider
        extcloud = ExtCloud(self.provider)

        # Update resource
        extzone = extcloud.dns_list_zones(name=self.domain.domain)[0]

        # Get list of records already there, update or create them as necessary
        ext_aliases = {r['name']:r for r in extcloud.dns_list_records(extzone, types=['A'])}
        for alias, expected_ip in needed.items():
            if alias in ext_aliases and expected_ip==ext_aliases[alias]['value']:
                print(f"No update required for alias [{alias}], it is already set to [{expected_ip}]")
                continue
            try:
                print(f"Updating existing records for alias [{alias}]: {ext_aliases[alias]['value']} -> {expected_ip}")
            except KeyError:
                print(f"Creating new record for alias [{alias}]: {expected_ip}")

            extcloud.dns_upsert_record(extzone['vsubid'], alias, expected_ip)
