import io

from openpyxl import load_workbook

from core.testing import DataTestCase


class AfpTests(DataTestCase):
    def setUp(self):
        self.sign_in(self.account())

    def test_page_and_data_are_the_regions_cases(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["data"]["regionName"], "Upper East")
        data = self.client.get("/api/data").json()
        self.assertTrue(data["cases"])
        self.assertEqual(data["districts"][0], ["BAW", "Bawku Municipal"])

    def test_schema_offers_only_the_accounts_region(self):
        sc = self.client.get("/api/schema").json()
        self.assertEqual([r["name"] for r in sc["regions"]], ["Upper East"])
        self.assertTrue(self.client.get("/api/next-epid?code=BAW").json()["epid"].startswith("GHA-UPE-BAW-"))

    def test_download_for_update_then_upload_it_back(self):
        r = self.client.get("/api/register.xlsx")
        self.assertIn("attachment;", r["Content-Disposition"])
        load_workbook(io.BytesIO(r.content))
        r = self.client.post("/api/import?name=cases.xlsx", r.content, content_type="application/octet-stream")
        self.assertEqual(r.status_code, 200, r.content)

    def test_a_case_not_entered_in_the_app_cannot_be_edited_here(self):
        epid = self.client.get("/api/data").json()["cases"][0]["epid"]
        r = self.client.get("/api/case?epid=" + epid)
        self.assertEqual(r.status_code, 403)
