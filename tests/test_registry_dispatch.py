import asyncio
import unittest

from registry import CommandRegistry, DispatchContext, PermissionDenied


class RegistryDispatchTests(unittest.TestCase):
    def test_accepts_comma_and_exclamation_with_comma_in_usage(self):
        registry = CommandRegistry()
        registry.register("ping", aliases=("p",), help="alive")
        self.assertEqual(("ping", "now"), registry.parse(",ping now"))
        self.assertEqual(("p", ""), registry.parse("!p"))
        self.assertIsNone(registry.parse("ping"))
        self.assertEqual(",ping", registry.all_specs()[0].usage)

    def test_permissions_disabled_and_room_requirements_are_enforced(self):
        registry = CommandRegistry()
        registry.register("admin", level="admin")
        registry.register("room", needs_room=True)
        user = DispatchContext(user="u", room="", level="user")
        with self.assertRaises(PermissionDenied):
            registry.authorize(registry.get("admin"), user)
        with self.assertRaises(PermissionDenied):
            registry.authorize(registry.get("room"), user)
        with self.assertRaises(PermissionDenied):
            registry.authorize(registry.get("admin"), DispatchContext("a", "R", "admin", ("admin",)))

    def test_room_admin_command_requires_global_or_current_room_authority(self):
        registry = CommandRegistry()
        registry.register("warn", room_admin=True)
        with self.assertRaises(PermissionDenied):
            registry.authorize(
                registry.get("warn"),
                DispatchContext("ordinary", "Room", "user"),
            )
        registry.authorize(
            registry.get("warn"),
            DispatchContext("local-mod", "Room", "user", room_authority=True),
        )
        registry.authorize(
            registry.get("warn"),
            DispatchContext("global-mod", "Room", "admin"),
        )

    def test_dispatch_invokes_real_handler(self):
        calls = []

        async def handler(bot, context):
            calls.append((context.user_key, context.args))

        registry = CommandRegistry()
        registry.register("echo", handler=handler)
        context = DispatchContext(" Straße ", "Room", "user")
        self.assertTrue(asyncio.run(registry.dispatch(None, context, ",echo hello")))
        self.assertEqual([("strasse", "hello")], calls)
        self.assertEqual("echo", context.invoked_name)


if __name__ == "__main__":
    unittest.main()
