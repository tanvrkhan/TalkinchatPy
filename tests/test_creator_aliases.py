import unittest

from services.auth import AccessControl


class AccessControlTests(unittest.TestCase):
    def test_creator_and_admin_matching_is_casefolded(self):
        access = AccessControl("Straße", ["Alice"], creator_aliases=["🆂🅷🅴🆁🆁🆈"])
        self.assertEqual("creator", access.level_of(" STRASSE "))
        self.assertEqual("creator", access.level_of("🆂🅷🅴🆁🆁🆈"))
        self.assertEqual("admin", access.level_of("ALICE"))
        self.assertEqual("user", access.level_of("Bob"))

    def test_room_authority_is_scoped_to_the_current_room(self):
        access = AccessControl("owner", [], room_authorities={"My Room": ["Alice"]})
        self.assertTrue(access.has_level("Alice", "admin", room="my room", allow_room_admin=True))
        self.assertFalse(access.has_level("Alice", "admin", room="Other", allow_room_admin=True))


if __name__ == "__main__":
    unittest.main()
