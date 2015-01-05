import grp
import json
import ldap, ldap.modlist
import os
import pwd
import shutil
import sys

from arkos.core.utilities import hashpw


class Users(object):
    def __init__(self, uri="", rootdn="", dn="cn=admin", config=None):
        if not all([uri, rootdn, dn]) and not config:
            raise Exception("No configuration values passed")
        self.uri = uri or config.get("general", "ldap_uri", "ldap://localhost")
        self.rootdn = rootdn or config.get("general", "ldap_rootdn", "dc=arkos-servers,dc=org")
        if os.path.isfile(os.path.join(sys.path[0], 'secrets.json')):
            secrets = os.path.join(sys.path[0], 'secrets.json')
        else:
            secrets = "/etc/arkos/secrets.json"
        with open(secrets, "r") as f:
            data = json.loads(f.read())
            if data.has_key("ldap"):
                data = data["ldap"]
            else:
                raise Exception("Admin LDAP credentials not found in secrets file")
        self.udb = self.authenticate(dn, data)
        if not self.udb:
            raise Exception("Admin LDAP authentication failed.")

    def authenticate(self, dn, passwd, admin=False):
        c = ldap.initialize(self.uri)
        try:
            c.simple_bind_s("%s,%s" % (dn, self.rootdn), passwd)
            if admin:
                data = c.search_s("cn=admins,ou=groups,%s" % self.rootdn,
                    ldap.SCOPE_SUBTREE, "(objectClass=*)", ["member"])[0]["member"]
                if (dn+","+self.rootdn) not in data:
                    return False
            return c
        except ldap.INVALID_CREDENTIALS:
            return False

    def get_users(self):
        r = []
        for x in self.udb.search_s("ou=users,%s" % self.rootdn, ldap.SCOPE_SUBTREE,
             "(objectClass=inetOrgPerson)", None):
            r.append(x[1])
        return r

    def get_system_users(self):
        r = []
        for x in pwd.getpwall():
            r.append({"username": x.pw_name, "uid": x.pw_uid, "gid": x.pw_gid,
                "dir": x.pw_dir, "shell": x.pw_shell, "groups": []})
        r = self.map_groups(r, self.get_groups())
        sf = lambda x: -1 if x["uid"]==0 else (x["uid"]+1000 if x["uid"]<1000 else x["uid"]-1000)
        return sorted(r, key=sf)

    def get_groups(self):
        r = []
        for x in grp.getgrall():
            r.append({"name": x.gr_name, "gid": x.gr_gid, "users": x.gr_mem})
        return r

    def map_groups(self, users, groups):
        for u in users:
            u["groups"] = []
            for g in groups:
                if u["username"] in g["users"]:
                    u["groups"].append(g["name"])
            u["groups"] = sorted(u["groups"])
        return users

    def get_user(self, name, users):
        for x in users:
            if x["username"] == name:
                return x
        return None

    def get_group(self, name, groups):
        for x in groups:
            if x["name"] == name:
                return x
        return None

    def add_user(self, attrs, admin=False, sudo=False):
        uid = str(self.get_next_uid())
        ldif = {
            "objectClass": ["mailAccount", "inetOrgPerson", "posixAccount"],
            "givenName": attrs["firstname"],
            "sn": attrs["lastname"],
            "displayName": attrs["firstname"]+" "+attrs["lastname"],
            "cn": attrs["firstname"]+" "+attrs["lastname"],
            "uid": attrs["username"],
            "mail": attrs["username"]+"@"+attrs["domain"],
            "maildrop": attrs["username"],
            "userPassword": hashpw(attrs["password"], "crypt"),
            "gidNumber": uid,
            "uidNumber": uid,
            "homeDirectory": "/home/%s" % attrs["username"],
            "loginShell": "/usr/bin/bash"
            }
        ldif = ldap.modlist.addModlist(ldif)
        self.udb.add_s("uid=%s,ou=users,%s" % (attrs["username"],self.rootdn), ldif)
        if admin:
            ldif = self.udb.search_s("cn=admins,ou=groups,%s" % self.rootdn,
                ldap.SCOPE_SUBTREE, "(objectClass=*)", None)[0][1]
            memlist = self.udb.search_s("cn=admins,ou=groups,%s" % self.rootdn,
                ldap.SCOPE_SUBTREE, "(objectClass=*)", ["member"])[0][1]["member"]
            memlist += "uid=%s,ou=users,%s" % (attrs["username"],self.rootdn)
            ldif = ldap.modlist.modifyModlist(ldif, {"member": memlist},
                ignore_oldexistent=1)
            self.udb.modify_ext_s("cn=admins,ou=groups,%s" % self.rootdn, ldif)
        if sudo:
            ldif = {
                "objectClass": ["sudoRole", "top"],
                "cn": attrs["username"],
                "sudoHost": "ALL",
                "sudoCommand": "ALL",
                "sudoUser": attrs["username"],
                "sudoOption": "authenticate"
            }
            ldif = ldap.modlist.addModlist(ldif)
            self.udb.add_s("cn=%s,ou=sudo,%s" % (attrs["username"], self.rootdn), ldif)

    def edit_user(self, attrs, admin=None, sudo=None):
        ldif = self.udb.search_s("uid=%s,ou=users,%s" % (attrs["username"],self.rootdn),
            ldap.SCOPE_SUBTREE, "(objectClass=inetOrgPerson)", None)[0][1]
        for x in ldif:
            if type(ldif[x]) == list and len(ldif[x]) == 1:
                ldif[x] = ldif[x][0]
        attrs = {
            "givenName": attrs.get("firstname") or ldif["givenName"],
            "sn": attrs.get("lastname") or ldif["sn"],
            "displayName": "%s %s" % ((attrs.get("firstname") or ldif["givenName"]),(attrs.get("lastname") or ldif["sn"])),
            "cn": "%s %s" % ((attrs.get("firstname") or ldif["givenName"]),(attrs.get("lastname") or ldif["sn"])),
            "mail": (ldif["uid"]+"@"+attrs.get("domain")) or ldif["mail"],
            "userPassword": hashpw(attrs["password"], "crypt") if attrs.get("password") else ldif["userPassword"],
        }
        nldif = ldap.modlist.modifyModlist(ldif, nldif, ignore_oldexistent=1)
        self.udb.modify_ext_s("uid=%s,ou=users,%s" % (ldif["username"],self.rootdn), nldif)
        if admin in [True, False]:
            nldif = self.udb.search_s("cn=admins,ou=groups,%s" % self.rootdn,
                ldap.SCOPE_SUBTREE, "(objectClass=*)", None)[0][1]
            memlist = self.udb.search_s("cn=admins,ou=groups,%s" % self.rootdn,
                ldap.SCOPE_SUBTREE, "(objectClass=*)", ["member"])[0][1]["member"]
            if admin == True:
                memlist += "uid=%s,ou=users,%s" % (ldif["uid"],self.rootdn)
            else:
                try:
                    memlist.remove("uid=%s,ou=users,%s" % (ldif["uid"],self.rootdn))
                except:
                    pass
            nldif = ldap.modlist.modifyModlist(nldif, {"member": memlist},
                ignore_oldexistent=1)
        if sudo == True:
            nldif = {
                "objectClass": ["sudoRole", "top"],
                "cn": ldif["uid"],
                "sudoHost": "ALL",
                "sudoCommand": "ALL",
                "sudoUser": ldif["uid"],
                "sudoOption": "authenticate"
            }
            nldif = ldap.modlist.addModlist(nldif)
            self.udb.add_s("cn=%s,ou=sudo,%s" % (ldif["uid"], self.rootdn), nldif)
        elif sudo == False:
            self.udb.delete_s("cn=%s,ou=sudo,%s" % (ldif["uid"], self.rootdn))

    def del_user(self, v, home=False):
        if home:
            hdir = self.udb.search_s("uid=%s,ou=users,%s" % (v,self.rootdn),
                ldap.SCOPE_SUBTREE, "(objectClass=*)", ["homeDirectory"])[0][1]["homeDirectory"]
            shutil.rmtree(hdir)
        self.udb.delete_s("uid=%s,ou=users,%s" % (v,self.rootdn))

    def add_system_user(self, v, home=False):
        shell("useradd -%sm %s" % ("r" if home else "", v))

    def del_system_user(self, v, rmhome=False):
        shell("userdel %s%s" % ("-r " if rmhome else "", v))

    def add_group(self, v):
        ldif = {
            "objectClass": ["posixGroup", "top"],
            "cn": v,
            "gidNumber": str(self.get_next_gid())
        }
        ldif = ldap.modlist.addModlist(ldif)
        self.udb.add_s("cn=%s,ou=groups,%s" % (v,self.rootdn), ldif)

    def del_group(self, v):
        self.udb.delete_s("cn=%s,ou=groups,%s" % (v,self.rootdn))

    def add_system_group(self, v):
        shell("groupadd %s" % v)

    def del_system_group(self, v):
        shell("groupdel %s" % v)

    def add_to_group(self, u, v):
        ldif = self.udb.search_s("cn=%s,ou=groups,%s" % (v,self.rootdn),
            ldap.SCOPE_SUBTREE, "(objectClass=*)", None)[0][1]
        memlist = self.udb.search_s("cn=%s,ou=groups,%s" % (v,self.rootdn),
            ldap.SCOPE_SUBTREE, "(objectClass=*)", ["memberUid"])[0][1]["memberUid"]
        ldif = ldap.modlist.modifyModlist(ldif, {"memberUid": memlist + [u]},
            ignore_oldexistent=1)
        self.udb.modify_ext_s("cn=%s,ou=groups,%s" % (v,self.rootdn), ldif)

    def add_to_system_group(self, u, v):
        shell("usermod -a -G %s %s" % (v, u))

    def remove_from_group(self, u, v):
        ldif = self.udb.search_s("cn=%s,ou=groups,%s" % (v,self.rootdn),
            ldap.SCOPE_SUBTREE, "(objectClass=*)", None)[0][1]
        memlist = self.udb.search_s("cn=%s,ou=groups,%s" % (v,self.rootdn),
            ldap.SCOPE_SUBTREE, "(objectClass=*)", ["memberUid"])[0][1]["memberUid"]
        ldif = ldap.modlist.modifyModlist(ldif, {"memberUid": [x for x in memlist if x != v]},
            ignore_oldexistent=1)
        self.udb.modify_ext_s("cn=%s,ou=groups,%s" % (v,self.rootdn), ldif)

    def change_user_password(self, u, p):
        ldif = self.udb.search_s("uid=%s,ou=users,%s" % (u,self.rootdn),
            ldap.SCOPE_SUBTREE, "(objectClass=*)", None)[0][1]
        ldif = ldap.modlist.modifyModlist(ldif, {"userPassword": hashpw(p, "crypt")},
            ignore_oldexistent=1)
        self.udb.modify_ext_s("uid=%s,ou=users,%s" % (u,self.rootdn), ldif)

    def change_user_system_password(self, u, l):
        shell('passwd %s' % u, stdin='%s\n%s\n' % (l,l))

    def get_next_uid(self):
        return max([x["uid"] for x in self.get_system_users()]) + 1

    def get_next_gid(self):
        return max([x["gid"] for x in self.get_groups()]) + 1
    
    def get_domains(self):
        results = []
        qset = self.udb.search_s("ou=domains,%s" % self.rootdn,
            ldap.SCOPE_SUBTREE, "virtualdomain=*", ["virtualdomain"])
        for x in qset:
            results.append(x[1]["virtualdomain"][0])
        return results
    
    def add_domain(self, domain):
        ldif = {"virtualdomain": domain, "objectClass": ["mailDomain", "top"]}
        self.udb.add_s("virtualdomain=%s,ou=domains,%s" % (domain,self.rootdn),
            ldap.modlist.addModlist(ldif))
    
    def remove_domain(self, domain):
        self.udb.delete_s("virtualdomain=%s,ou=domains,%s" % (domain,self.rootdn))
