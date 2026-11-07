import json
from django.contrib.auth.models import User

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

    def test_dhims2_calls_name_the_app(self):
        """DHIMS2's firewall refuses Python's default User-Agent (Cloudflare error 1010)."""
        from unittest import mock

        from . import dhims2
        seen = {}

        class Answer:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"displayName": "Test"}'

        def fake_urlopen(req, timeout):
            seen.update(req.header_items())
            return Answer()
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            self.assertEqual(dhims2.call("me", url=dhims2.DEFAULT_URL, tok="d2pat_x")["displayName"], "Test")
        self.assertEqual(seen.get("User-agent"), dhims2.USER_AGENT)

    def test_dhims2_token_stays_with_the_sign_in(self):
        """Not remembered: kept in the signed-in user's server-side session, so every process of the app (cPanel runs
        several) has it on the next request; never lent to another account; failures are logged without it."""
        import io
        import urllib.error
        from unittest import mock

        from . import dhims2
        seen = []

        class Answer:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps(self.body).encode()

        def fake_urlopen(req, timeout):
            seen.append(req.get_header("Authorization"))
            if "dataSets" in req.full_url:
                return Answer({"dataSets": []})
            if "fail" in req.full_url:
                raise urllib.error.HTTPError(req.full_url, 409, "Conflict", {}, io.BytesIO(b'{"message": "Dimension dx is not valid"}'))
            return Answer({"displayName": "Officer"})
        post = lambda o: self.client.post("/api/idsr/dhims2/connect", json.dumps(o), content_type="application/json")
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            self.sign_in(self.account(region="North East"))
            self.assertEqual(post({"url": dhims2.DEFAULT_URL, "token": "d2pat_mine", "remember": False}).status_code, 200)
            dhims2._request_token.set(None)  # as in another process: only the session knows the token
            r = self.client.get("/api/idsr/dhims2")
            self.assertTrue(r.json()["hasToken"])
            self.assertFalse(dhims2.load().get("token"))  # not written to disk
            with self.assertLogs("idsr.dhims2", "ERROR") as logs:
                with self.assertRaises(ValueError):
                    dhims2.call("fail")
            self.assertIn("HTTP 409", logs.output[0])
            self.assertIn("Dimension dx is not valid", logs.output[0])
            self.assertNotIn("d2pat_mine", "".join(logs.output))
            # another account does not get it
            dhims2._request_token.set(None)
            self.sign_in(self.account("ue-other", region="Upper East"))
            self.assertFalse(self.client.get("/api/idsr/dhims2").json()["hasToken"])
            # forgetting ends it
            self.sign_in(User.objects.get(username="ue-officer"))
            self.client.post("/api/idsr/dhims2/forget", "{}", content_type="application/json")
            self.assertFalse(self.client.get("/api/idsr/dhims2").json()["hasToken"])
        self.assertIn("ApiToken d2pat_mine", seen)

    def test_dhims2_region_found_by_name_when_its_id_is_not_on_dhims2(self):
        """A region id that is not on DHIMS2 (fQbPWKMUava came from another server's export) is looked up by name,
        used and remembered, and the fetch goes on."""
        import io
        import urllib.error
        import urllib.parse
        from unittest import mock

        from core import orgunits

        from . import dhims2
        asked = []

        class Answer:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps(self.body).encode()

        def fake_urlopen(req, timeout):
            url = urllib.parse.unquote(req.full_url)
            asked.append(url)
            if "organisationUnits/fQbPWKMUava" in url:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(
                    b'{"message": "OrganisationUnit with id fQbPWKMUava could not be found."}'))
            if "organisationUnits?" in url:
                return Answer({"organisationUnits": [{"id": "UpperEast01", "name": "Upper East Region", "level": 2},
                                                     {"id": "SubDist0001", "name": "Upper East Sub", "level": 4}]})
            if "analytics" in url:
                return Answer({"headers": [{"name": n} for n in ("dx", "pe", "ou", "value")], "rows": [],
                               "metaData": {"items": {}}})
            return Answer({})
        self.assertEqual(orgunits.region_of("Upper East")["id"], "ggEw5nfApv3")  # DHIMS2's own id
        unit = orgunits.region_of("Upper East") | {"id": "fQbPWKMUava"}  # an id from another server's export
        with mock.patch("urllib.request.urlopen", fake_urlopen), mock.patch.object(dhims2, "token", return_value="d2pat_x"):
            self.assertEqual(dhims2.region_id(unit), ("UpperEast01", 2))
            self.assertEqual(dhims2.load()["orgUnitIds"]["Upper East"], ["UpperEast01", 2])
            n = len(asked)
            self.assertEqual(dhims2.region_id(unit), ("UpperEast01", 2))  # remembered: DHIMS2 not asked again
            self.assertEqual(len(asked), n)
            from . import store as idsr_store
            dhims2.fetch(idsr_store.store_for("Upper East"), "Z6AHGS4ZpiJ", {"afp.CS": "AbCdEfGhIjK"}, 2026, 44, 44)
        self.assertTrue(any("ou:UpperEast01;LEVEL-3" in u for u in asked), asked[-2:])

    def test_dhims2_settings_never_show_the_token(self):
        self.sign_in(self.account(region="North East"))
        self.assertNotIn("token", self.client.get("/api/idsr/dhims2").json())
