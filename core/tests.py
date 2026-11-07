import json

from .testing import DataTestCase


class StartPageTests(DataTestCase):
    def test_regional_account_sees_only_its_region(self):
        self.sign_in(self.account(region="North East"))
        data = self.client.get("/start").context["data"]
        self.assertTrue(data["locked"])
        self.assertEqual([r["name"] for r in data["regions"]], ["North East"])
        r = self.client.post("/api/region", json.dumps({"region": "Volta"}), content_type="application/json")
        self.assertEqual(r.status_code, 403)

    def test_national_account_picks_a_region_for_this_sign_in(self):
        self.sign_in(self.account("nat", region="Ghana"))
        data = self.client.get("/start").context["data"]
        self.assertEqual((data["selected"], data["regions"][0]["name"]), ("Ghana", "Ghana"))
        self.assertEqual(len(data["regions"]), 17)
        r = self.client.post("/api/region", json.dumps({"region": "Volta Region"}), content_type="application/json")
        self.assertEqual(r.json(), {"region": "Volta"})
        self.assertEqual(self.client.get("/start").context["data"]["selected"], "Volta")
        self.assertEqual(self.client.get("/api/data").json()["regionName"], "Volta")

    def test_templates_link_their_static_files(self):
        self.sign_in(self.account())
        html = self.client.get("/start").content.decode()
        self.assertIn("/static/core/css/base.css", html)
        self.assertIn('id="page-data"', html)
