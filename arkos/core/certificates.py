import glob
import hashlib
import OpenSSL
import os

from arkos.core Framework
from arkos.core.utility import dictfilter


class Certificates(Framework):
    REQUIRES = ["apps", "sites", "config"]

    def on_init(self):
        if not self.config:
            raise Exception("No configuration values passed")
        cert_dir = self.config.get('certificates', 'cert_dir')
        if not os.path.exists(cert_dir):
            os.mkdir(cert_dir)
        key_dir = self.config.get('certificates', 'key_dir')
        if not os.path.exists(key_dir):
            os.mkdir(key_dir)
        ca_cert_dir = self.config.get('certificates', 'ca_cert_dir')
        if not os.path.exists(ca_cert_dir):
            os.mkdir(ca_cert_dir)
        ca_key_dir = self.config.get('certificates', 'ca_key_dir')
        if not os.path.exists(ca_key_dir):
            os.mkdir(ca_key_dir)
        if not self.users.get_group("ssl-cert", self.users.get_groups()):
            self.users.add_group("ssl-cert")
        self.gid = users.get_group("ssl-cert", self.users.get_groups())["gid"]

    def get(self, **kwargs):
        certs = []
        if self.storage:
            certs = self.storage.get_list("certificates")
        if not self.storage or not certs:
            certs = self.scan_certs()
        if not self.storage:
            self.Storage.append_all("certificates", certs)
        return dictfilter(certs, kwargs)

    def scan(self):
        certs, assigns = [], {}
        for x in self.apps.get(ssl=True) + self.sites.get(ssl=True):
            data = {'type': x["type"], 'name': x["name"]}
            assigns[x["cert_name"]].append(data) if assigns.has_key(x["cert_name"]) else assigns[x["cert_name"]] = [data]
        if self.config.get('genesis', 'ssl'):
            ssl = os.path.splitext(os.path.basename(self.Config.get('genesis', 'cert_file', '')))[0]
            if ssl and assigns.has_key(ssl):
                assigns[ssl].append({'type': 'genesis'})
            elif ssl:
                assigns[ssl] = [{'type': 'genesis'}]
        for x in glob.glob(os.path.join(self.cert_dir, '*.crt')):
            name = os.path.splitext(os.path.basename(x))[0]
            with open(x, 'r') as f:
                c = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, f.read())
            with open(os.path.join(self.key_dir, name+'.key'), 'r') as f:
                k = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM, f.read())
            sha1, md5 = self.get_key_hashes(k)
            certs.append({"name": name, 
                "cert_path": os.path.join(self.cert_dir, name+'.crt'),
                "key_path": os.path.join(self.key_dir, name + '.key'),
                "keytype": "RSA" if k.type() == OpenSSL.crypto.TYPE_RSA else ("DSA" if k.type() == OpenSSL.crypto.TYPE_DSA else "Unknown"), 
                "keylength": int(k.bits()), "domain": c.get_subject().CN,
                "assign": assigns[name] if assigns.has_key(name) else [], 
                "expiry": c.get_notAfter(),
                "sha1": sha1,
                "md5": md5
                })
        return certs

    def get_cas(self, **kwargs):
        cas = []
        if self.storage:
            cas = self.storage.get_list("certificates:authorities")
        if not self.storage or not cas:
            cas = self.scan_cas()
        if self.storage:
            self.storage.append_all("certificates:authorities", cas)
        return dictfilter(cas, kwargs)

    def scan_cas(self):
        # Find all certificate authorities generated by arkOS
        # and return basic information
        certs = []
        for x in glob.glob(os.path.join(self.ca_cert_dir, '*.pem')):
            name = os.path.splitext(os.path.split(x)[1])[0]
            with open(x, 'r') as f:
                cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, f.read())
            with open(os.path.join(os.path.join(self.ca_key_dir, name+'.key')), 'r') as f:
                key = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM, f.read())
            certs.append({'name': name, 'expiry': cert.get_notAfter()})
        return certs

    def upload(self, name, cert, key, chain='', assign=[]):
        try:
            crt = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, cert)
        except Exception, e:
            raise Exception('Could not read certificate file. Please make sure you\'ve selected the proper file.', e)
        try:
            ky = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM, key)
        except Exception, e:
            raise Exception('Could not read private keyfile. Please make sure you\'ve selected the proper file.', e)
        
        with open(os.path.join(self.cert_dir, name+'.crt'), 'w') as f:
            f.write(cert)
            if chain:
                f.write('\n') if not cert.endswith('\n') else None
                f.write(chain)
        with open(os.path.join(self.key_dir, name+'.key'), 'w') as f:
            f.write(key)

        os.chown(os.path.join(self.cert_dir, name + '.crt'), -1, self.gid)
        os.chmod(os.path.join(self.cert_dir, name + '.crt'), 0660)
        os.chown(os.path.join(self.key_dir, name + '.key'), -1, self.gid)
        os.chmod(os.path.join(self.key_dir, name + '.key'), 0660)

        sha1, md5 = self.get_key_hashes(ky)
        cert = {"name": name, 
            "cert_path": os.path.join(self.cert_dir, name+'.crt'),
            "key_path": os.path.join(self.key_dir, name + '.key'),
            "keytype": "RSA" if ky.type() == OpenSSL.crypto.TYPE_RSA else ("DSA" if ky.type() == OpenSSL.crypto.TYPE_DSA else "Unknown"), 
            "keylength": int(ky.bits()), "domain": crt.get_subject().CN,
            "assign": [], "expiry": crt.get_notAfter(),
            "sha1": sha1,
            "md5": md5
            }
        if self.storage:
            self.storage.append("certificates", cert)
        return cert

    def create(self, name, vars, keytype, keylength, hostname):
        # Check to see that we have a CA ready
        basehost = ".".join(hostname.split(".")[-2:])
        if not self.get_cas(hostname=basehost):
            self.create_authority(basehost)
            ca = self.get_cas(hostname=basehost)
        with open(ca["cert_path"]) as f:
            ca_cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, f.read())
        with open(ca["key_path"]) as f:
            ca_key = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM, f.read())

        cert_path = os.path.join(self.cert_dir, name+'.crt')
        key_path = os.path.join(self.key_dir, name+'.key')

        # Generate a key, then use it to sign a new cert
        keytype = OpenSSL.crypto.TYPE_DSA if keytype == 'DSA' else OpenSSL.crypto.TYPE_RSA
        keylength = int(keylength)
        try:
            key = OpenSSL.crypto.PKey()
            key.generate_key(keytype, keylength)
            crt = OpenSSL.crypto.X509()
            crt.set_version(3)
            if vars.getvalue('certcountry', ''):
                crt.get_subject().C = vars.getvalue('certcountry')
            if vars.getvalue('certsp', ''):
                crt.get_subject().ST = vars.getvalue('certsp')
            if vars.getvalue('certlocale', ''):
                crt.get_subject().L = vars.getvalue('certlocale')
            if vars.getvalue('certcn', ''):
                crt.get_subject().CN = vars.getvalue('certcn')
            if vars.getvalue('certemail', ''):
                crt.get_subject().emailAddress = vars.getvalue('certemail')
            crt.get_subject().O = 'arkOS Servers'
            crt.set_serial_number(int(self.SystemTime.get_serial_time()))
            crt.gmtime_adj_notBefore(0)
            crt.gmtime_adj_notAfter(2*365*24*60*60)
            crt.set_issuer(ca_cert.get_subject())
            crt.set_pubkey(key)
            crt.sign(ca_key, 'sha256')
        except Exception, e:
            raise Exception('Error generating self-signed certificate: '+str(e))

        with open(cert_path, "wt") as f:
            f.write(OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, crt))
        os.chown(cert_path, -1, self.gid)
        os.chmod(cert_path, 0660)

        with open(key_path, "wt") as f:
            f.write(OpenSSL.crypto.dump_privatekey(OpenSSL.crypto.FILETYPE_PEM, key))
        os.chown(key_path, -1, self.gid)
        os.chmod(key_path, 0660)

        sha1, md5 = self.get_key_hashes(key)
        cert = {"name": name, 
            "cert_path": cert_path,
            "key_path": key_path,
            "keytype": keytype, 
            "keylength": keylength, "domain": vars.getvalue('certcn'),
            "assign": [], "expiry": crt.get_notAfter(),
            "sha1": sha1,
            "md5": md5
            }
        if self.storage:
            self.storage.append("certificates", cert)
        return cert

    def create_authority(self, hostname):
        key = OpenSSL.crypto.PKey()
        key.generate_key(OpenSSL.crypto.TYPE_RSA, 2048)

        ca = OpenSSL.crypto.X509()
        ca.set_version(3)
        ca.set_serial_number(int(self.SystemTime.get_serial_time()))
        ca.get_subject().O = 'arkOS Servers'
        ca.get_subject().CN = hostname
        ca.gmtime_adj_notBefore(0)
        ca.gmtime_adj_notAfter(5*365*24*60*60)
        ca.set_issuer(ca.get_subject())
        ca.set_pubkey(key)
        ca.add_extensions([
            OpenSSL.crypto.X509Extension("basicConstraints", True, "CA:TRUE, pathlen:0"),
            OpenSSL.crypto.X509Extension("keyUsage", True, "keyCertSign, cRLSign"),
            OpenSSL.crypto.X509Extension("subjectKeyIdentifier", False, "hash", subject=ca),
        ])
        ca.sign(key, 'sha256')
        with open(os.path.join(self.ca_cert_dir, hostname+'.pem'), "wt") as f:
            f.write(OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, ca))
        os.chmod(os.path.join(self.ca_cert_dir, hostname+'.pem'), 0660)
        with open(os.path.join(self.ca_key_path, hostname+'.key'), "wt") as f:
            f.write(OpenSSL.crypto.dump_privatekey(OpenSSL.crypto.FILETYPE_PEM, key))
        auth = {"name": hostname, "cert_path": cert_path, "key_path": key_path}
        if self.storage:
            self.storage.append("certificates:authorities", auth)
        return auth

    def assign(self, cert, assign):
        # Assign a certificate to plugins/webapps as listed
        for x in assign:
            if x[0] == 'genesis':
                self.config.set('genesis', 'cert_file', cert["cert_path"])
                self.config.set('genesis', 'cert_key', cert["key_path"])
                self.config.set('genesis', 'ssl', True)
                self.config.save()
            elif x[0] == 'website':
                self.sites.ssl_enable(x[1], cert)
                self.sites.nginx_reload()
            elif x[0] == 'plugin':
                self.config.set('ssl_'+x[1].pid, 'cert', name)
                self.config.save()
                x[1].enable_ssl(cert)

    def unassign(self, assign):
        if assign == 'genesis':
            self.config.set("genesis", "cert_file", "")
            self.config.set("genesis", "cert_key", "")
            self.config.set("genesis", "ssl", False)
            self.config.save()
        elif assign[0] == 'website':
            self.sites.ssl_disable(assign[1])
            self.sites.nginx_reload()
        elif assign[0] == 'plugin':
            self.config.set('ssl_'+assign[1].pid, 'cert', '')
            self.config.save()
            assign[1].disable_ssl()

    def remove(self, cert):
        # Remove cert, key and control file for associated name
        for x in self.apps.get(ssl=True, cert_name=cert["name"]):
            PluginControl().disable_ssl()
        for x in self.sites.get(ssl=True, cert_name=cert["name"]):
            self.sites.ssl_disable(x)
            self.sites.nginx_reload()
        if self.config.get("genesis", "ssl") and self.config.get("genesis", "cert_file") == cert["cert_path"]:
            self.config.set("genesis", "cert_file", "")
            self.config.set("genesis", "cert_key", "")
            self.config.set("genesis", "ssl", False)
            self.config.save()
        if self.storage:
            self.storage.remove("certificates", cert)
        self.unlink(cert)

    def remove_authority(self, ca):
        if self.storage:
            self.storage.remove("certificates:authorities", ca)
        self.unlink(ca)

    def unlink(self, cert):
        if os.path.exists(cert["cert_path"]):
            os.unlink(cert["cert_path"])
        if os.path.exists(cert["key_path"]):
            os.unlink(cert["key_path"])

    def get_key_hashes(self, key):
        h, m = hashlib.sha1(), hashlib.md5()
        h.update(OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_ASN1, key))
        m.update(OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_ASN1, key))
        h, m = h.hexdigest(), m.hexdigest()
        return {"sha1": ":".join([h[i:i+2].upper() for i in range(0,len(h), 2)]), 
            "md5": ":".join([m[i:i+2].upper() for i in range(0,len(m), 2)])}
