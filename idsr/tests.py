import json

from core.testing import DataTestCase


class IdsrTests(DataTestCase):
    def test_page_and_data_for_the_accounts_region(self):
        self.sign_in(self.account(region="North East"))
        r = self.client.get("/idsr")
        self.assertEqual(r.status_code, 200)
        self.assertIn('id="bulletinCss"', r.content.decode())  # the PNG export reads it, so it stays inline
        data = self.client.get("/api/idsr/data?region=North%20East").json()
        self.assertEqual(data["region"], "North East")
        self.assertTrue(data["districts"])

    def test_other_regions_are_refused(self):
        self.sign_in(self.account(region="North East"))
        r = self.client.get("/api/idsr/data?region=Volta")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"], "Your account is for North East Region only.")

    def test_save_a_week_then_download_it(self):
        self.sign_in(self.account(region="Volta"))
        r = self.client.post("/api/idsr/week?region=Volta", json.dumps({"year": 2026, "week": 40, "meta": {}, "counts": {}}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["data"]["saved"])
        r = self.client.get("/api/idsr/week.csv?region=Volta&year=2026&week=40")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r["Content-Type"])

    def test_only_support_deletes_a_week(self):
        self.sign_in(self.account(region="North East"))
        r = self.client.post("/api/idsr/week/delete", json.dumps({"year": 2026, "week": 43}), content_type="application/json")
        self.assertEqual(r.status_code, 403)

    def test_dhims2_settings_never_show_the_token(self):
        self.sign_in(self.account(region="North East"))
        self.assertNotIn("token", self.client.get("/api/idsr/dhims2").json())
