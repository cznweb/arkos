"""
Classes and functions for managing file sharing services.

arkOS Core
(c) 2016 CitizenWeb
Written by Jacob Cook
Licensed under GPLv3, see LICENSE.md
"""

from arkos import logger, storage, signals, applications


class Sharer:
    """
    Represents a file sharing service.

    A file sharing service can be designed to operate either on a local area
    network, or instead to be a sync client for devices on the Internet.
    """

    def __init__(self, id="", name="", icon=""):
        """
        Initialize the sharer object.

        :param str id: File sharing service ID
        :param str name: File sharing service display name
        :param str icon: FontAwesome icon class
        """
        self.id = id
        self.name = name or self.name
        self.icon = icon

    def get_shares(self):
        """Reimplement this to return a list of Share objects."""

    @property
    def as_dict(self):
        """Return sharer metadata as dict."""
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon
        }

    @property
    def serialized(self):
        """Return serializable sharer metadata as dict."""
        return self.as_dict


class Share:
    """Represents a file share object."""

    def __init__(self, id="", comment="", path="", valid_users=[],
                 public=True, readonly=False, manager=None):
        """Initialize."""
        self.id = id
        self.comment = comment
        self.path = path
        self.valid_users = valid_users
        self.public = public
        self.readonly = readonly
        self.manager = manager

    def add_share(self):
        """Reimplement this with actions to add a share."""

    def remove_share(self):
        """Reimplement this with actions to remove a share."""

    def add(self, *args, **kwargs):
        """Add a file share."""
        signals.emit("shares", "pre_add", self)
        self.add_share()
        storage.shares[self.id] = self
        signals.emit("shares", "post_add", self)

    def remove(self, *args, **kwargs):
        """Remove a file share."""
        signals.emit("shares", "pre_remove", self)
        self.remove_share()
        if self.id in storage.shares:
            del storage.shares[self.id]
        signals.emit("shares", "post_remove", self)

    @property
    def as_dict(self):
        """Return share metadata as dict."""
        return {
            "id": self.id,
            "share_type": self.manager.id,
            "comment": self.comment,
            "path": self.path,
            "valid_users": self.valid_users,
            "public": self.public,
            "read_only": self.readonly,
            "is_ready": True
        }

    @property
    def serialized(self):
        """Return serializable share metadata as dict."""
        return self.as_dict


class Mount:
    """Represents a file share mount object."""

    def __init__(self, path="", network_path="", readonly=False,
                 username="", password="", is_mounted=False, manager=None):
        """Initialize."""
        self.path = path
        self.network_path = network_path
        self.readonly = readonly
        self.is_mounted = is_mounted
        self.manager = manager
        self.username = username
        self.password = password

    @property
    def id(self):
        """Reimplement this with the generated mount ID."""

    def mount(self):
        """Reimplement this with actions to mount a share."""

    def umount(self):
        """Reimplement this with actions to unmount a share."""

    def add(self, *args, **kwargs):
        """Mount a file share."""
        signals.emit("shares", "pre_mount", self)
        self.mount()
        storage.mounts[self.id] = self
        signals.emit("shares", "post_mount", self)

    def remove(self, *args, **kwargs):
        """Unmount a file share."""
        signals.emit("shares", "pre_umount", self)
        self.umount()
        if self.id in storage.mounts:
            del storage.mounts[self.id]
        signals.emit("shares", "post_umount", self)

    @property
    def as_dict(self):
        """Return mount metadata as dict."""
        return {
            "id": self.id,
            "share_type": self.manager.id,
            "path": self.path,
            "network_path": self.network_path,
            "is_mounted": self.is_mounted,
            "read_only": self.readonly,
            "is_ready": True
        }

    @property
    def serialized(self):
        """Return serializable mount metadata as dict."""
        return self.as_dict


def get_shares(id=None, type=None):
    """
    Retrieve a list of all file shares registered with arkOS.

    :param str id: If present, obtain one share that matches this ID
    :param str type: Filter by ``fs-samba``, ``fs-afp``, etc
    :return: Share(s)
    :rtype: Share or list thereof
    """
    data = storage.shares
    if not data:
        data = scan_shares()
    if id:
        return data.get(id)
    if type:
        return filter(lambda x: x.manager.id == type, data.values())
    return data.values()


def scan_shares():
    """
    Retrieve a list of all file shares registered with arkOS.

    :return: Share(s)
    :rtype: Share or list thereof
    """
    storage.shares.clear()
    for x in get_sharers():
        try:
            for y in x.get_shares():
                storage.shares[y.id] = y
        except Exception as e:
            logger.warning(
                "Sharers", "Could not get shares for {0}".format(x.name)
            )
            logger.debug("Sharers", str(e))
    return storage.shares


def get_mounts(id=None, type=None):
    """
    Retrieve a list of all file share mounts registered with arkOS.

    :param str id: If present, obtain one mount that matches this ID
    :param str type: Filter by ``fs-samba``, ``fs-afp``, etc
    :return: Mount(s)
    :rtype: Mount or list thereof
    """
    data = storage.mounts
    if not data:
        data = scan_mounts()
    if id:
        return data.get(id)
    if type:
        return filter(lambda x: x.manager.id == type, data.values())
    return data.values()


def scan_mounts():
    """
    Retrieve a list of all file share mounts registered with arkOS.

    :return: Mount(s)
    :rtype: Mount or list thereof
    """
    storage.mounts.clear()
    for x in get_sharers():
        try:
            for y in x.get_mounts():
                storage.mounts[y.id] = y
        except:
            continue
    return storage.mounts


def get_sharers(id=None):
    """
    Retrieve a list of all file share systems registered with arkOS.

    :param str id: If present, obtain one sharer that matches this ID
    :return: Sharer(s)
    :rtype: Sharer or list thereof
    """
    data = storage.share_engines
    if not data:
        data = scan_sharers()
    if id:
        return data.get(id)
    return data.values()


def scan_sharers():
    """
    Retrieve a list of all file share systems registered with arkOS.

    :return: Sharer(s)
    :rtype: Sharer or list thereof
    """
    storage.share_engines.clear()
    for x in applications.get(type="fileshare"):
        if x.installed and hasattr(x, "_share_mgr"):
            storage.share_engines[x.id] = x._share_mgr(id=x.id, icon=x.icon)
    return storage.share_engines
