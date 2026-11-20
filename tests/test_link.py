import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bridge  # noqa: E402
import link  # noqa: E402
from tests.test_bridge import FakeHttp, Resp  # noqa: E402

CHILD = "5a4d0b0c-0000-4000-8000-000000000011"
TOKEN = "miara_pat_" + "ab" * 20
LINK = {"token": TOKEN, "code": "WDJB-MJHT", "url": "https://getmiara.com/link?code=WDJB-MJHT", "expires_in": 600, "interval": 3}


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class SetupTest(unittest.TestCase):
    def run_setup(self, *answers, children=None):
        clock = Clock()
        http = FakeHttp(Resp(200, LINK), *answers, Resp(200, {"children": children or [{"id": CHILD, "name": "Juniper"}]}))
        client = bridge.Client("https://example.test/api/v1", "", http=http, sleep=clock.sleep)
        lines = []
        env = Path(tempfile.mkdtemp()) / ".env"
        env.write_text("# mine\nDEVICE_USER=me\nMIARA_TOKEN=old\n")
        code = link.setup(client, env_file=env, name="Nursery bridge", out=lines.append, sleep=clock.sleep, clock=clock,
                          open_browser=lambda url: False)
        return code, http, "\n".join(lines), env, clock

    def test_approved_saves_the_token_and_the_only_child(self):
        code, http, text, env, clock = self.run_setup(Resp(200, {"status": "pending"}), Resp(200, {"status": "approved"}))
        self.assertEqual(code, 0)
        start = http.calls[0]
        self.assertEqual((start["method"], start["url"]), ("POST", "https://example.test/api/v1/links"))
        self.assertEqual(start["body"], {"name": "Nursery bridge", "scopes": ["write:events", "write:observations"]})
        self.assertEqual([c["method"] + " " + c["url"].rsplit("/", 1)[1] for c in http.calls[1:]],
                         ["GET links", "GET links", "GET children"])
        self.assertTrue(all(c["headers"]["Authorization"] == f"Bearer {TOKEN}" for c in http.calls[1:]), "polls with the link's token")
        self.assertEqual(clock.t, 3, "waits the interval between polls")
        self.assertIn("WDJB-MJHT", text)
        self.assertIn("getmiara.com/link?code=WDJB-MJHT", text)
        self.assertIn("It writes to Juniper", text)
        saved = env.read_text()
        self.assertIn(f"MIARA_TOKEN={TOKEN}\n", saved)
        self.assertNotIn("MIARA_TOKEN=old", saved)
        self.assertIn(f"MIARA_CHILD_ID={CHILD}\n", saved)
        self.assertIn("DEVICE_USER=me", saved, "other lines stay")
        self.assertEqual(env.stat().st_mode & 0o777, 0o600)

    def test_several_children_lists_them_and_leaves_the_child_to_you(self):
        kids = [{"id": CHILD, "name": "Juniper"}, {"id": "x", "name": "Arlo"}]
        code, _, text, env, _ = self.run_setup(Resp(200, {"status": "approved"}), children=kids)
        self.assertEqual(code, 0)
        self.assertNotIn("MIARA_CHILD_ID", env.read_text())
        self.assertIn("Arlo: x", text)

    def test_denied_or_expired_saves_nothing(self):
        for status, words in (("denied", "turned down"), ("expired", "ran out")):
            code, _, text, env, _ = self.run_setup(Resp(200, {"status": status}))
            self.assertEqual(code, 1)
            self.assertIn(words, text)
            self.assertIn("MIARA_TOKEN=old", env.read_text())

    def test_stops_waiting_when_the_link_runs_out(self):
        code, http, text, _, clock = self.run_setup(Resp(200, {"status": "pending"}))
        self.assertEqual(code, 1)
        self.assertIn("ran out", text)
        self.assertLessEqual(clock.t, 610)

    def test_opens_the_browser_when_it_can(self):
        opened = []
        http = FakeHttp(Resp(200, LINK), Resp(200, {"status": "approved"}), Resp(200, {"children": []}))
        client = bridge.Client("https://example.test/api/v1", "", http=http)
        lines = []
        link.connect(client, out=lines.append, open_browser=lambda url: opened.append(url) or True)
        self.assertEqual(opened, [LINK["url"]])
        self.assertIn("Opened Miara in your browser", lines[0])

    def test_bridge_setup_command(self):
        http = FakeHttp(Resp(200, LINK), Resp(200, {"status": "denied"}))
        with mock.patch.object(link, "has_browser", return_value=False), mock.patch.object(link, "write_env_value"):
            code = bridge.main(["setup", "--name", "Nursery bridge", "--read"], http=http, sleep=lambda s: None)
        self.assertEqual(code, 1)
        self.assertEqual(http.calls[0]["body"]["scopes"], ["write:events", "write:observations", "read"])


if __name__ == "__main__":
    unittest.main()
