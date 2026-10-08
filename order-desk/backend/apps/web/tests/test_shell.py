"""The UI shell is public, cache-free and contains no customer or session data."""

from django.contrib.staticfiles import finders
from django.test import SimpleTestCase


class WorkspaceShellTests(SimpleTestCase):
    def test_public_shell_and_same_origin_assets(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'src="/static/desk/main.js"')
        self.assertContains(response, 'href="/static/desk/desk.css"')
        self.assertContains(response, 'autocomplete="current-password"')
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertNotIn("sessionid", response.cookies)
        for asset in (
            "desk/main.js",
            "desk/api.js",
            "desk/controller.js",
            "desk/desk.css",
        ):
            with self.subTest(asset=asset):
                self.assertIsNotNone(finders.find(asset))

    def test_shell_accepts_head_and_rejects_mutations(self) -> None:
        self.assertEqual(self.client.head("/").status_code, 200)
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                self.assertEqual(getattr(self.client, method)("/").status_code, 405)
