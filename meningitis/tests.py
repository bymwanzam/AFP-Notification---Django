import io
import json
from datetime import date, timedelta

from django.test import SimpleTestCase
from openpyxl import Workbook, load_workbook

from core.testing import DataTestCase

from . import choices as ch
from .models import Case, SubDistrict, ThresholdConfig
from .reports import KINDS, thresholds, status

TODAY = date.today()
SEEN = TODAY - timedelta(days=10)


def form(**kw):
    """A complete, valid case for the form."""
    base = {"last_name": "Abdul", "first_name": "Rahi", "district": "Gushegu", "date_seen": SEEN.isoformat(),
            "date_onset": (SEEN - timedelta(days=2)).isoformat(), "age_years": "12", "sex": "M", "fever": "1",
            "neck_stiffness": "1", "outcome": "1", "vaccinated": "2", "specimen_collected": "1", "final_result": "03",
            "final_classification": "1"}
    return base | kw


def legacy_workbook(rows, other_rows=()):
    """A workbook laid out like the regional line list: title rows, headings, then the Table14 header in row 6."""
    headers = ["LastName", "FirstName", "CCC", "RRR", "DDD", "YY", "NNNNN", "EPID", "Epi Week", "HealthFacility",
               "Subdistrict", "Subdistrict2", "District", "DistrictOrigin", "Village", "AgeMonths", "AgeYears", "Sex",
               "DateConsultation", "Onset", "Fever", "NeckStiff", "Headache", "Other", "Outcome", "Immu", "Vaccine1",
               "Vaccine2", "PCV", "VaccineOther", "SpecimenCollected", "DateSpecimenCollected", "Gram", "TDR", "Latex",
               "Culture", "PCR", "FinalResult", "FinalClassification", "Observations", "Filter"]
    wb = Workbook()
    wb.active.title = "Instructions"
    for title, data in (("Outbreak linelist", rows), ("Outbreak linelist-other region", other_rows)):
        ws = wb.create_sheet(title)
        ws.append(["", "Country:", "GHANA"])
        ws.append(["", "Region:", "NORTHERN"])
        ws.append([])
        ws.append(["No.", "Surname"])
        ws.append([])
        ws.append([""] + headers)
        for r in data:
            ws.append([""] + [r.get(h, "") for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class CodeListTests(SimpleTestCase):
    def test_old_spellings_read_back_to_the_codes(self):
        cases = [("yesno", "9 unknown", "9"), ("yesno", "Missing", "9"), ("yesno", "Yes", "1"), ("yesno", "NO", "2"),
                 ("gram", "2 GND", "2"), ("gram", "1-GPD", "1"), ("outcome", "1-Recovered", "1"), ("outcome", "3 on treatment ", "3"),
                 ("vaccine", "1-MenAfriVac", "1"), ("vaccine", "3-MenACW ", "3"), ("pcv", "2-No", "4"), ("pcv", "PCV13-2", "2"),
                 ("pathogen", "03-NmW", "03"), ("pathogen", "08-S. pneumoniae", "08"), ("pathogen", "14-Negative", "14"),
                 ("classification", "1 Confirmed ", "1"), ("sex", "female", "F"), ("pathogen", 3.0, "03")]
        for name, raw, code in cases:
            self.assertEqual(ch.normalise(name, raw), (code, None), (name, raw))

    def test_blank_and_unreadable(self):
        self.assertEqual(ch.normalise("yesno", "  "), (None, None))
        self.assertIsNone(ch.normalise("gram", "purple")[0])

    def test_thresholds_by_population(self):
        cfg = ThresholdConfig(region="Northern")
        self.assertEqual(thresholds(50000, cfg)[:2], (1.5, 5.0))  # 3 and 10 per 100,000
        self.assertEqual(thresholds(20000, cfg)[:2], (2, 5))       # small population: case counts
        self.assertEqual(thresholds(None, cfg)[2], "no population")
        limits = thresholds(50000, cfg)
        self.assertEqual([status(n, limits) for n in (0, 1, 2, 5)], ["", "", "alert", "epidemic"])


class MeningitisTests(DataTestCase):
    def setUp(self):
        self.user = self.sign_in(self.account("nr-officer", region="Northern"))

    def post(self, path, obj):
        return self.client.post(path, json.dumps(obj), content_type="application/json")

    def add(self, **kw):
        r = self.post("/api/men/case/save", {"fields": form(**kw)})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    # ---------- pages ----------
    def test_page_and_start(self):
        r = self.client.get("/meningitis")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["data"]["region"], "Northern")
        self.assertEqual(len(r.context["data"]["districts"]), 16)
        self.assertContains(self.client.get("/start"), 'id="goMen"')

    # ---------- entry ----------
    def test_new_case_gets_its_epid_and_epi_week(self):
        a, b = self.add(), self.add(last_name="Other")
        yy = f"{SEEN.year % 100:02d}"
        self.assertEqual(a["epid"], f"GHA-NOR-GUS-{yy}-00001")
        self.assertEqual(b["epid"], f"GHA-NOR-GUS-{yy}-00002")
        case = Case.objects.get(pk=a["id"])
        self.assertEqual((case.epi_year, case.epi_week), SEEN.isocalendar()[:2])
        self.assertEqual(self.client.get(f"/api/men/next-epid?district=GUS&year={yy}").json()["sequence"], 3)

    def test_checks(self):
        bad = form(date_onset=(SEEN + timedelta(days=1)).isoformat(), vaccinated="2", vaccine_1="1", age_months="5")
        r = self.post("/api/men/case/save", {"fields": bad})
        self.assertEqual(r.status_code, 400)
        fields = {e["field"] for e in r.json()["errors"]}
        self.assertTrue({"date_onset", "vaccinated", "age_months"} <= fields, fields)
        r = self.post("/api/men/case/save", {"fields": form(district="Bolgatanga Municipal")})
        self.assertEqual(r.json()["errors"][0]["field"], "district")

    def test_confirmed_without_a_result_is_a_warning_not_an_error(self):
        w = self.add(final_result="14")["warnings"]
        self.assertEqual(w[0]["field"], "final_classification")

    def test_the_same_epid_twice_is_refused(self):
        self.add(sequence_no="7")
        r = self.post("/api/men/case/save", {"fields": form(sequence_no="7")})
        self.assertEqual(r.status_code, 400)
        self.assertIn("already in the line list", r.json()["errors"][0]["msg"])

    def test_edit_logs_the_change(self):
        a = self.add()
        f = self.client.get(f"/api/men/case?id={a['id']}").json()["fields"]
        r = self.post("/api/men/case/save", {"id": a["id"], "fields": f | {"outcome": "2"}})
        self.assertEqual(r.status_code, 200, r.content)
        hist = self.client.get(f"/api/men/case?id={a['id']}").json()["history"]
        self.assertEqual(hist[0]["action"], "Changed")
        self.assertEqual(hist[0]["changes"][0][1:], ["1-Alive", "2-Dead"])

    def test_living_in_another_region_is_listed_apart(self):
        self.add(residence_district="Bawku West")
        self.add()
        self.assertEqual(self.client.get("/api/men/cases?other=1").json()["total"], 1)
        rep = self.client.get(f"/api/men/report?kind=regional&year={SEEN.isocalendar()[0]}").json()
        self.assertEqual((rep["cases"], rep["otherRegion"]), (1, 1))

    # ---------- access ----------
    def test_regions_see_only_their_cases_and_the_national_view_only_reads(self):
        a = self.add()
        self.sign_in(self.account("ue-officer", region="Upper East"))
        self.assertEqual(self.client.get("/api/men/cases").json()["total"], 0)
        self.assertEqual(self.client.get(f"/api/men/case?id={a['id']}").status_code, 404)
        self.sign_in(self.account("national", region="Ghana"))
        self.assertEqual(self.client.get("/api/men/cases").json()["total"], 1)
        self.assertEqual(self.post("/api/men/case/save", {"fields": form()}).status_code, 403)

    def test_only_the_person_who_entered_a_case_deletes_it(self):
        a = self.add()
        self.sign_in(self.account("nr-other", region="Northern"))
        self.assertEqual(self.post("/api/men/case/delete", {"id": a["id"]}).status_code, 403)
        self.sign_in(self.user)
        self.assertEqual(self.post("/api/men/case/delete", {"id": a["id"]}).status_code, 200)
        self.assertFalse(Case.objects.exists())

    # ---------- reports ----------
    def test_every_report_adds_up_to_the_line_list(self):
        SubDistrict.objects.create(region="Northern", district="Gushegu", name="Galwei", population=40000)
        sub = SubDistrict.objects.get(name="Galwei")
        for i in range(4):
            self.add(residence_subdistrict=str(sub.id), outcome="2" if i == 0 else "1")
        self.add(district="Karaga", age_years="", age_months="6", final_classification="3", final_result="")
        self.add(district="Saboba", final_classification="")
        year = SEEN.isocalendar()[0]
        listed = self.client.get(f"/api/men/cases?year={year}&other=0").json()["total"]
        self.assertEqual(listed, 6)
        for kind in KINDS:
            rep = self.client.get(f"/api/men/report?kind={kind}&year={year}").json()
            self.assertEqual(rep["cases"], listed, kind)
        weekly = self.client.get(f"/api/men/report?kind=weekly&year={year}").json()
        self.assertEqual((weekly["total"]["cases"], weekly["total"]["deaths"]), (6, 1))
        galwei = next(r for g in weekly["groups"] for r in g["rows"] if r["label"] == "Galwei")
        self.assertEqual((galwei["cases"], galwei["alert"], galwei["epidemic"]), (4, 1.2, 4.0))
        self.assertIn("epidemic", galwei["status"])
        regional = self.client.get(f"/api/men/report?kind=regional&year={year}").json()
        self.assertEqual(sum(a["cases"] for a in regional["ages"]), 6)
        self.assertEqual(next(a for a in regional["ages"] if a["label"] == "<2")["cases"], 1)
        self.assertEqual(regional["total"]["cfr"], 16.7)
        dash = self.client.get(f"/api/men/report?kind=dashboard&year={year}&district=Gushegu").json()
        self.assertEqual(dash["cases"], 4)
        for kind in ("weekly", "district", "regional", "epicurve", "vaccination", "laboratory", "thresholds", "dashboard"):
            r = self.client.get(f"/api/men/report.xlsx?kind={kind}&year={year}")
            self.assertEqual(r.status_code, 200, kind)
            load_workbook(io.BytesIO(r.content))

    # ---------- upload and downloads ----------
    def test_upload_the_regional_workbook(self):
        yy = f"{SEEN.year % 100:02d}"
        rows = [
            {"LastName": "Iddi", "CCC": "GHA", "RRR": "NOR", "DDD": "KAR", "YY": yy, "NNNNN": 12, "District": "Karaga",
             "Subdistrict": "Pishigu", "DateConsultation": SEEN, "Onset": SEEN, "AgeYears": 7, "Sex": "F", "Immu": "9 unknown",
             "SpecimenCollected": "1-Yes", "Gram": "2 GND", "FinalResult": "03-NmW", "FinalClassification": "1-Confirmed",
             "Outcome": "Missing"},
            {"LastName": "No number", "District": "Karaga"},  # Filter 0: skipped
            {"LastName": "Bad", "CCC": "GHA", "RRR": "NOR", "DDD": "XXX", "YY": yy, "NNNNN": 1, "District": "Nowhere"},
        ]
        other = [{"EPID": f"GHA-NOR-TAM-{yy}-00003", "District": "Tamale", "DistrictOrigin": "Bawku West",
                  "DateConsultation": SEEN.strftime("%d/%m/%Y"), "AgeYears": 30}]
        body = legacy_workbook(rows, other)
        r = self.client.post("/api/men/import?name=linelist.xlsx", body, content_type="application/octet-stream")
        self.assertEqual(r.status_code, 200, r.content)
        plan = r.json()
        self.assertEqual((plan["counts"]["added"], plan["skipped"], plan["counts"]["errors"]), (2, 1, 1))
        self.assertEqual(plan["newSubdistricts"], ["Pishigu (Karaga)"])
        self.assertFalse(Case.objects.exists())  # the review saves nothing
        r = self.client.post("/api/men/import?name=linelist.xlsx&apply=1", body, content_type="application/octet-stream")
        self.assertTrue(r.json()["saved"])
        c = Case.objects.get(epid=f"GHA-NOR-KAR-{yy}-00012")
        self.assertEqual((c.vaccinated, c.gram, c.outcome, c.reporting_subdistrict.name), ("9", "2", "9", "Pishigu"))
        self.assertTrue(Case.objects.get(epid=f"GHA-NOR-TAM-{yy}-00003").other_region)
        # the same file again changes nothing; a changed cell updates, a blank one never erases
        self.assertEqual(self.client.post("/api/men/import?name=l.xlsx&apply=1", body, content_type="application/octet-stream").json()["unchanged"], 2)
        rows[0] |= {"Outcome": "2-Dead", "Sex": ""}
        r = self.client.post("/api/men/import?name=l.xlsx&apply=1", legacy_workbook(rows[:1]), content_type="application/octet-stream").json()
        self.assertEqual(r["counts"]["updated"], 1)
        c.refresh_from_db()
        self.assertEqual((c.outcome, c.sex), ("2", "F"))

    def test_download_without_names_then_upload_it_back(self):
        self.add()
        r = self.client.get("/api/men/linelist.xlsx")
        ws = load_workbook(io.BytesIO(r.content)).active
        headers = [c.value for c in ws[4]]
        self.assertNotIn("LastName", headers)
        self.assertEqual(headers[headers.index("NNNNN") + 1], "EPID")
        r = self.client.post("/api/men/import?name=back.xlsx", r.content, content_type="application/octet-stream")
        self.assertEqual(r.json()["unchanged"], 1, r.content)
        with_names = load_workbook(io.BytesIO(self.client.get("/api/men/linelist.xlsx?names=1").content)).active
        self.assertEqual(with_names.cell(row=5, column=1).value, "Abdul")

    def test_subdistricts_and_thresholds(self):
        r = self.post("/api/men/subdistricts", {"rows": [{"district": "Gushegu", "name": "Katani", "population": "12000"},
                                                         {"district": "Mars", "name": "X"}]})
        self.assertEqual([s["name"] for s in r.json()["subdistricts"]], ["Katani"])
        self.assertEqual(len(r.json()["problems"]), 1)
        r = self.post("/api/men/thresholds", {"alertRate": 5, "epidemicRate": 15, "cutoff": 30000, "alertCases": 2,
                                              "epidemicCases": 5, "seasonStart": 40})
        self.assertEqual(r.json()["cfg"]["seasonStart"], 40)
        r = self.post("/api/men/thresholds", {"alertRate": 20, "epidemicRate": 10, "cutoff": 1, "alertCases": 2,
                                              "epidemicCases": 5, "seasonStart": 40})
        self.assertEqual(r.status_code, 400)
