"""Protocol-independent TalkinChat authorization rules."""

from transports.talkinchat import normalize_identity


LEVELS = {"user": 0, "admin": 1, "creator": 2}


class AccessControl:
    def __init__(self, creator, admins=(), room_authorities=None,
                 creator_aliases=()):
        self.creator = normalize_identity(creator)
        self.creators = {
            self.creator,
            *(normalize_identity(value) for value in creator_aliases),
        }
        self.admins = {normalize_identity(value) for value in admins}
        self.room_authorities = {
            normalize_identity(room): {normalize_identity(user) for user in users}
            for room, users in (room_authorities or {}).items()
        }

    def level_of(self, username):
        user = normalize_identity(username)
        if user in self.creators:
            return "creator"
        if user in self.admins:
            return "admin"
        return "user"

    def has_level(self, username, required, *, room="", allow_room_admin=False):
        if LEVELS[self.level_of(username)] >= LEVELS.get(required, 0):
            return True
        if allow_room_admin and required == "admin":
            users = self.room_authorities.get(normalize_identity(room), set())
            return normalize_identity(username) in users
        return False
