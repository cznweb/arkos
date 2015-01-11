import grp
import json
import ldap, ldap.modlist
import os
import pwd
import shutil
import sys

import groups

from arkos import conns
from arkos.utilities import hashpw


class User(object):
    def __init__(
            self, name="", first_name="", last_name="", uid=0, domain="", 
            rootdn="dc=arkos-servers,dc=org", admin=False, sudo=False):
        self.name = name
        self.first_name = first_name
        self.last_name = last_name
        self.uid = uid or get_next_uid()
        self.domain = domain
        self.rootdn = rootdn
        self.admin = admin
        self.sudo = sudo
    
    def add(self, passwd):
        try:
            ldif = conns.LDAP.search_s("uid=%s,ou=users,%s" % (self.name,self.rootdn),
                ldap.SCOPE_SUBLIST, "(objectClass=*)", None)
            raise Exception("A user with this name already exists")
        except ldap.NO_SUCH_OBJECT:
            pass

        ldif = {
            "objectClass": ["mailAccount", "inetOrgPerson", "posixAccount"],
            "givenName": self.first_name,
            "sn": self.last_name,
            "displayName": self.first_name+" "+self.last_name,
            "cn": self.first_name+" "+self.last_name,
            "uid": self.name,
            "mail": self.name+"@"+self.domain,
            "maildrop": self.name,
            "userPassword": hashpw(passwd, "crypt"),
            "gidNumber": self.uid,
            "uidNumber": self.uid,
            "homeDirectory": "/home/%s" % self.name,
            "loginShell": "/usr/bin/bash"
            }
        ldif = ldap.modlist.addModlist(ldif)
        conns.LDAP.add_s("uid=%s,ou=users,%s" % (self.name,self.rootdn), ldif)
        self.update_adminsudo()
    
    def update(self):
        try:
            ldif = conns.LDAP.search_s("uid=%s,ou=users,%s" % (self.name,self.rootdn),
                ldap.SCOPE_SUBLIST, "(objectClass=*)", None)
        except ldap.NO_SUCH_OBJECT:
            raise Exception("This user does not exist")

        ldif = ldif[0][1]
        for x in ldif:
            if type(ldif[x]) == list and len(ldif[x]) == 1:
                ldif[x] = ldif[x][0]
        attrs = {
            "givenName": self.first_name,
            "sn": self.last_name,
            "displayName": "%s %s" % (self.first_name, self.last_name),
            "cn": "%s %s" % (self.first_name, self.last_name),
            "mail": self.name+"@"+self.domain
        }
        nldif = ldap.modlist.modifyModlist(ldif, attrs, ignore_oldexistent=1)
        conns.LDAP.modify_ext_s("uid=%s,ou=users,%s" % (self.name,self.rootdn), nldif)
        self.update_adminsudo()

    def update_adminsudo(self):
        nldif = conns.LDAP.search_s("cn=admins,ou=groups,%s" % self.rootdn,
            ldap.SCOPE_SUBTREE, "(objectClass=*)", None)[0][1]
        memlist = nldif["member"]
        
        if admin and "uid=%s,ou=users,%s"%(self.name,self.rootdn) not in memlist:
            memlist += "uid=%s,ou=users,%s" % (self.name,self.rootdn)
            nldif = ldap.modlist.modifyModlist(nldif, {"member": memlist}, 
                ignore_oldexistent=1)
            conns.LDAP.modify_ext_s("cn=admins,ou=groups,%s" % self.rootdn, nldif)
        elif not admin and "uid=%s,ou=users,%s"%(self.name,self.rootdn) in memlist:
            memlist.remove("uid=%s,ou=users,%s" % (self.name,self.rootdn))
            nldif = ldap.modlist.modifyModlist(nldif, {"member": memlist},
                ignore_oldexistent=1)
            conns.LDAP.modify_ext_s("cn=admins,ou=groups,%s" % self.rootdn, nldif)

        try:
            conns.LDAP.search_s("cn=%s,ou=sudo,%s" % (self.name,self.rootdn),
                ldap.SCOPE_SUBLIST, "(objectClass=*)", None)
            is_sudo = True
        except ldap.NO_SUCH_OBJECT:
            is_sudo = False

        if sudo and not is_sudo:
            nldif = {
                "objectClass": ["sudoRole", "top"],
                "cn": self.name,
                "sudoHost": "ALL",
                "sudoCommand": "ALL",
                "sudoUser": self.name,
                "sudoOption": "authenticate"
            }
            nldif = ldap.modlist.addModlist(nldif)
            conns.LDAP.add_s("cn=%s,ou=sudo,%s" % (self.name, self.rootdn), nldif)
        elif not sudo and is_sudo:
            conns.LDAP.delete_s("cn=%s,ou=sudo,%s" % (self.name, self.rootdn))
    
    def verify_passwd(self, passwd):
        try:
            c = ldap.initialize("ldap://localhost")
            c.simple_bind_s("uid=%s,ou=users,%s" % (self.name, self.rootdn), passwd)
            data = c.search_s("cn=admins,ou=groups,%s" % self.rootdn,
                ldap.SCOPE_SUBTREE, "(objectClass=*)", ["member"])[0]["member"]
            if "uid=%s,ou=users,%s" % (self.name, self.rootdn) not in data:
                return False
            return True
        except ldap.INVALID_CREDENTIALS:
            return False

    def delete(self, delete_home=True):
        self.admin, self.sudo = False, False
        self.update_adminsudo()
        if delete_home:
            hdir = conns.LDAP.search_s("uid=%s,ou=users,%s" % (v,self.rootdn),
                ldap.SCOPE_SUBTREE, "(objectClass=*)", ["homeDirectory"])[0][1]["homeDirectory"]
            shutil.rmtree(hdir)
        conns.LDAP.delete_s("uid=%s,ou=users,%s" % (v,self.rootdn))


class SystemUser(object):
    def __init__(self, name="", uid=0, groups=[]):
        self.name = name
        self.uid = uid or get_next_uid()
        self.groups = groups
    
    def add(self):
        shell("useradd -rm %s" % self.name)
    
    def update(self):
        for x in self.groups:
            shell("usermod -a -G %s %s" % (x, self.name))
    
    def update_password(self, passwd):
        shell('passwd %s' % u, stdin='%s\n%s\n' % (self.name,passwd,passwd))
    
    def delete(self):
        shell("userdel %s" % self.name)


def get(uid=None):
    r = []
    for x in conns.LDAP.search_s("ou=users,%s" % self.rootdn, ldap.SCOPE_SUBTREE,
         "(objectClass=inetOrgPerson)", None):
        u = User(name=x[1]["uid"], uid=int(x[1]["uidNumber"]), 
            first_name=x[1]["givenName"], last_name=x[1]["sn"],
            domain=x[1]["mail"].split("@")[1], rootdn=x[0].split("ou=users,")[1])

        try:
            conns.LDAP.search_s("cn=%s,ou=sudo,%s" % (self.name,self.rootdn),
                ldap.SCOPE_SUBLIST, "(objectClass=*)", None)
            u.sudo = True
        except ldap.NO_SUCH_OBJECT:
            u.sudo = False

        memlist = conns.LDAP.search_s("cn=admins,ou=groups,%s" % self.rootdn,
            ldap.SCOPE_SUBTREE, "(objectClass=*)", None)[0][1]["member"]
        if "uid=%s,ou=users,%s"%(u.name,u.rootdn) in memlist:
            u.admin = True
        else:
            u.admin = False

        if u.name == uid:
            return u
        r.append(u)
    return r if not uid else None

def get_system(uid=None):
    r = []
    for x in pwd.getpwall():
        su = SystemUser(name=x.pw_name, uid=x.pw_uid)
        for y in groups.get():
            if su.name in y.users:
                su.groups.append(y.name)
        if uid == su.name:
            return su
        r.append(su)
    return sorted(r, key=su.uid) if not uid else None

def get_next_uid():
    return max([x.uid for x in get_system()]) + 1