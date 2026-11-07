"""SMS reminders. Fish Africa is never called: its HTTP request is caught and answered here."""
import io
import json
import urllib.error
from datetime import date, timedelta
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from core.testing import DataTestCase

from . import letsfish, service
from .models import DistrictContact, ReminderLog

TODAY = date(2026, 11, 7)
CREDS = dict(LETSFISH_APP_ID="app123", LETSFISH_APP_SECRET="secret456", LETSFISH_SENDER_ID="GHS-AFP")


def case(epid, district, days_left, outcome="FUP Pending", name="Secret Patient"):
    onset = TODAY + timedelta(days=days_left) - timedelta(days=60)
    return {"epid": epid, "district": district, "onset": onset.isoformat(), "outcome": outcome, "name": name}


REGISTER = [
    case("GHA-UPE-BON-26-001", "Bongo", 5),              # due soon
    case("GHA-UPE-BON-26-002", "Bongo", -3),             # overdue, week 1
    case("GHA-UPE-BON-26-003", "Bongo", 20),             # not yet
    case("GHA-UPE-BON-26-004", "Bongo", -3, "FUP done"),  # done: never reminded
    case("GHA-UPE-GAR-26-001", "Garu", -10),             # overdue, week 2
]


class Answer:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return json.dumps(self.body).encode()


class RuleTests(SimpleTestCase):
    @override_settings(REMINDER_SOON_DAYS=7, REMINDER_REPEAT_DAYS=7)
    def test_stages(self):
        self.assertEqual([service.stage_of(d) for d in (8, 7, 0, -1, -7, -8, -15)],
                         [None, "soon", "soon", "past-1", "past-1", "past-2", "past-3"])

    def test_ghana_numbers(self):
        for raw in ("0244123456", "+233 24 412 3456", "233244123456", "00233244123456", "244123456"):
            self.assertEqual(letsfish.phone(raw), "233244123456", raw)
        for bad in ("12345", "0144123456", ""):
            with self.assertRaises(ValueError):
                letsfish.phone(bad)

    @override_settings(**CREDS)
    def test_the_request_follows_the_fish_africa_api(self):
        seen = {}

        def urlopen(req, timeout):
            seen.update(url=req.full_url, method=req.get_method(), headers=dict(req.header_items()), body=json.loads(req.data))
            return Answer({"success": True, "status": 202, "data": [{"recipient": "233244123456", "reference": "sms_1", "status": "queued"}]})
        with mock.patch("urllib.request.urlopen", urlopen):
            out = letsfish.send(["233244123456"], "Hello")
        self.assertEqual(out[0]["reference"], "sms_1")
        self.assertEqual((seen["url"], seen["method"]), ("https://api.letsfish.africa/v1/sms", "POST"))
        self.assertEqual(seen["headers"]["Authorization"], "Bearer app123.secret456")
        self.assertEqual(seen["headers"]["User-agent"], letsfish.USER_AGENT)  # Cloudflare refuses Python's default
        self.assertEqual(seen["body"], {"sender_id": "GHS-AFP", "message": "Hello", "recipients": ["233244123456"]})

    @override_settings(**CREDS)
    def test_errors_read_plainly(self):
        def broke(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 402, "Payment Required", {}, io.BytesIO(
                b'{"success": false, "error": {"status": 402, "title": "Insufficient balance"}}'))
        with mock.patch("urllib.request.urlopen", broke), self.assertRaisesRegex(letsfish.SmsError, "too little balance"):
            letsfish.send(["233244123456"], "Hi")

    @override_settings(LETSFISH_APP_ID="", LETSFISH_APP_SECRET="", LETSFISH_SENDER_ID="")
    def test_not_set_up(self):
        self.assertFalse(letsfish.status()["configured"])
        with self.assertRaisesRegex(letsfish.SmsError, "not set up"):
            letsfish.send(["233244123456"], "Hi")


@override_settings(**CREDS, REMINDER_SOON_DAYS=7, REMINDER_REPEAT_DAYS=7)
class ReminderTests(DataTestCase):
    def setUp(self):
        self.load = mock.patch("afp.cases.load_cases", return_value=REGISTER)
        self.load.start()
        self.addCleanup(self.load.stop)
        DistrictContact.objects.create(region="Upper East", district="Bongo", name="Bongo DSO", phone="233244000001")
        DistrictContact.objects.create(region="Upper East", district="", name="RSO", phone="233244000002")
        DistrictContact.objects.create(region="Upper East", district="Garu", name="Off", phone="233244000003", active=False)

    def test_who_gets_what(self):
        plan = {m.contact.name: m for m in service.plan(TODAY, "Upper East")}
        self.assertEqual(set(plan), {"Bongo DSO", "RSO"})  # Garu's officer is switched off
        self.assertEqual({d.epid for d in plan["Bongo DSO"].cases}, {"GHA-UPE-BON-26-001", "GHA-UPE-BON-26-002"})
        self.assertEqual(len(plan["RSO"].cases), 3)  # the whole region
        text = plan["Bongo DSO"].text
        self.assertIn("OVERDUE (1):\nGHA-UPE-BON-26-002 due 04/11, 3 d late", text)
        self.assertIn("DUE SOON (1):\nGHA-UPE-BON-26-001 due 12/11 (in 5 d)", text)
        self.assertNotIn("Secret", text)  # never patient names

    def test_each_stage_once_and_failures_retried(self):
        sent = []
        with mock.patch("reminders.letsfish.send", side_effect=lambda to, msg: sent.append(to) or [{"reference": "r"}]):
            service.run(TODAY, "Upper East")
            self.assertEqual(len(sent), 2)
            self.assertEqual(service.run(TODAY, "Upper East"), [])                     # same day: nothing new
            self.assertEqual(service.run(TODAY + timedelta(days=1), "Upper East"), [])  # same stages
            # 5 days on: BON-002 is 8 days late (overdue week 2), GAR-001 15 (week 3); BON-001 is due today, still "soon"
            later = service.run(TODAY + timedelta(days=5), "Upper East")
        self.assertEqual({(c["epid"], c["stage"]) for r in later for c in r["cases"]},
                         {("GHA-UPE-BON-26-002", "past-2"), ("GHA-UPE-GAR-26-001", "past-3")})
        ReminderLog.objects.all().delete()
        with mock.patch("reminders.letsfish.send", side_effect=letsfish.SmsError("The Fish Africa account has too little balance.")):
            out = service.run(TODAY, "Upper East")
        self.assertEqual(len(out), 1)  # stops at the first balance error
        self.assertFalse(ReminderLog.objects.filter(ok=True).exists())
        self.assertEqual(len(service.plan(TODAY, "Upper East")), 2)  # still to send

    def test_page_contacts_and_send_now(self):
        self.sign_in(self.support())  # works in Upper East until another region is picked
        r = self.client.get("/reminders")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["data"]["sms"]["configured"])
        self.assertNotIn("secret456", r.content.decode())
        post = lambda p, o: self.client.post(p, json.dumps(o), content_type="application/json")
        r = post("/api/sms/contacts", {"rows": [{"district": "Bawku West", "name": "BW DSO", "phone": "0244 000 004"},
                                               {"district": "Bawku West", "name": "Bad", "phone": "123"}]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["problems"]), 1)
        self.assertTrue(DistrictContact.objects.filter(name="BW DSO", phone="233244000004").exists())
        with mock.patch("reminders.letsfish.send", return_value=[{"reference": "r"}]):
            r = post("/api/sms/send", {})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(all(x["ok"] for x in r.json()["results"]))

    def test_who_can_do_what(self):
        post = lambda p, o: self.client.post(p, json.dumps(o), content_type="application/json")
        row = {"district": "Bongo", "name": "New DSO", "phone": "0244000009"}
        # a regional officer adds their own region's district officers, and only theirs
        self.sign_in(self.account())
        r = self.client.get("/reminders")
        self.assertEqual(r.status_code, 200)
        for panel in ('id="settingsPanel"', 'id="testPanel"', "Fish Africa settings"):
            self.assertNotContains(r, panel)  # not hidden: never in the page
        data = r.context["data"]
        self.assertFalse(data["support"])
        self.assertEqual(set(data["sms"]), {"configured"})  # no sender ID, no App ID ending
        self.assertIn('href="/reminders" data-m="sms">SMS reminders', self.client.get("/").content.decode())
        r = post("/api/sms/contacts", {"rows": [row]})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(DistrictContact.objects.filter(region="Upper East", name="New DSO").exists())
        north = DistrictContact.objects.create(region="Northern", district="Karaga", name="Not mine", phone="233244000010")
        post("/api/sms/contacts", {"rows": [], "delete": [north.id]})
        self.assertTrue(DistrictContact.objects.filter(pk=north.id).exists())  # another region's: untouched
        for path in ("/api/sms/settings", "/api/sms/send", "/api/sms/test"):
            r = post(path, {"appId": "x", "phone": "0244123456"})
            self.assertEqual(r.status_code, 403, path)
            self.assertIn("Only the support account", r.json()["error"])
        # a national administrator reads every region and changes nothing
        self.sign_in(self.account("national", region="Ghana"))
        r = self.client.get("/reminders")
        self.assertTrue(r.context["data"]["national"])
        self.assertNotContains(r, 'id="settingsPanel"')
        self.assertEqual(post("/api/sms/contacts", {"rows": [row]}).status_code, 403)
        # support: settings and sending, in the region it picks; the Ghana view sends nothing
        self.sign_in(self.support())
        r = self.client.get("/reminders")
        self.assertTrue(r.context["data"]["support"])
        self.assertContains(r, 'id="settingsPanel"')
        self.assertContains(r, 'id="testPanel"')
        post("/api/region", {"region": "Ghana"})
        self.assertEqual(post("/api/sms/send", {}).status_code, 403)

    @override_settings(LETSFISH_APP_ID="", LETSFISH_APP_SECRET="", LETSFISH_SENDER_ID="")
    def test_settings_on_the_page(self):
        self.sign_in(self.support())
        post = lambda o: self.client.post("/api/sms/settings", json.dumps(o), content_type="application/json")
        self.assertFalse(self.client.get("/api/sms/data").json()["sms"]["configured"])
        r = post({"appId": "app-0001-ABCD", "appSecret": "s3cret-value-xyz", "senderId": "GHS-AFP"})
        self.assertEqual(r.status_code, 200, r.content)
        sms = r.json()["sms"]
        self.assertEqual((sms["configured"], sms["source"], sms["appIdEnd"], sms["sender"]), (True, "page", "ABCD", "GHS-AFP"))
        self.assertNotIn("s3cret", r.content.decode() + self.client.get("/reminders").content.decode())
        self.assertEqual(letsfish.creds(), {"app_id": "app-0001-ABCD", "app_secret": "s3cret-value-xyz", "sender_id": "GHS-AFP"})
        post({"appId": "", "appSecret": "", "senderId": "GHS-AFP2"})  # blanks keep the saved ID and secret
        self.assertEqual(letsfish.creds()["app_secret"], "s3cret-value-xyz")
        self.assertEqual(post({"appId": "x", "appSecret": "", "senderId": "MUCH-TOO-LONG-ID"}).status_code, 400)
        self.assertFalse(post({"clear": True}).json()["sms"]["configured"])

    def test_the_page_wins_over_env(self):
        letsfish.save_settings("page-app-id", "page-secret-1", "PAGE")
        self.assertEqual(letsfish.creds()["app_id"], "page-app-id")
        letsfish.clear_settings()
        self.assertEqual(letsfish.creds()["app_id"], "app123")  # back to the settings (.env)

    def test_daily_command_dry_run(self):
        out = io.StringIO()
        with mock.patch("reminders.service.timezone.localdate", return_value=TODAY):
            call_command("send_reminders", "--dry-run", stdout=out)
        self.assertIn("WOULD SEND to Bongo DSO (Bongo) 233244000001", out.getvalue())
        self.assertFalse(ReminderLog.objects.exists())
