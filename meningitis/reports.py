"""The workbook's analyses, worked out from the line list with database aggregates (no loops over cases):

- weekly:      cases and deaths by sub-district and epi week, against each sub-district's alert and epidemic
               thresholds (the "Data Table" sheet)
- district:    cases and deaths by district and epi week (the "DistrictSum" sheet)
- regional:    cases, deaths and CFR by district, age band, pathogen and sub-district (the "RegionalSum" sheet)
- epicurve:    cases by epi week and final classification (the "Epi Curve" sheet)
- vaccination: vaccination status, outcome, specimens and data completeness ("Vaccination and indicators")
- laboratory:  Gram stain, rapid test, latex, culture, PCR and final result ("Laboratory results")
- thresholds:  one chart per sub-district: weekly cases and deaths against the alert and epidemic lines
- dashboard:   headline figures, the epi curve and each district's status in the latest week

Every report covers the same cases for the same filters: the cases of the period, of the region (or one district),
not living in another region. The totals of every report add up to that count.
"""
from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Case as When_, CharField, Count, IntegerField, Q, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from core import orgunits
from core.branding import unit_label

from . import choices as ch
from .cases import region_cases
from .models import SubDistrict, ThresholdConfig

KINDS = {
    "dashboard": "Dashboard", "weekly": "Weekly cases and deaths", "district": "District summary",
    "regional": "Regional summary", "epicurve": "Epi curve", "vaccination": "Vaccination and indicators",
    "laboratory": "Laboratory results", "thresholds": "Threshold charts",
}
AGE_BANDS = [("<2", 0, 2), ("2–4", 2, 5)] + [(f"{a}–{a + 4}", a, a + 5) for a in range(5, 60, 5)] + [("60+", 60, None)]
NOT_GIVEN = "(not given)"
DEATH = Q(outcome=ch.DEAD)


def weeks_in(year):
    return date(year, 12, 28).isocalendar()[1]


def pct(n, d):
    return round(100 * n / d, 1) if d else None


# ---------- filters ----------
@dataclass
class Filters:
    year: int
    season: bool
    wfrom: int
    wto: int
    district: str

    @classmethod
    def read(cls, get, unit):
        """From the query string: year, season=1 (from week 39 of the year before), from, to, district."""
        today = timezone.localdate()
        try:
            year = int(get.get("year") or today.isocalendar()[0])
        except ValueError:
            year = today.isocalendar()[0]
        year = min(max(year, 2000), 2100)
        last = weeks_in(year)

        def week(name, default):
            try:
                return min(max(int(get.get(name) or default), 1), last)
            except ValueError:
                return default
        wfrom, wto = week("from", 1), week("to", last)
        names = [n for _, n in unit["districts"]]
        district = get.get("district", "")
        return cls(year, get.get("season", "1") != "0", min(wfrom, wto), max(wfrom, wto), district if district in names else "")


class Period:
    """The epi weeks a report covers, in order: weeks season_start..end of the year before (season view), then
    from..to of the year."""

    def __init__(self, f, cfg):
        self.f, start = f, cfg.season_start_week
        prev = [(f.year - 1, w) for w in range(start, weeks_in(f.year - 1) + 1)] if f.season else []
        self.weeks = prev + [(f.year, w) for w in range(f.wfrom, f.wto + 1)]
        self.q = Q(epi_year=f.year, epi_week__gte=f.wfrom, epi_week__lte=f.wto)
        if f.season:
            self.q |= Q(epi_year=f.year - 1, epi_week__gte=start)
        self.index = {w: i for i, w in enumerate(self.weeks)}

    @property
    def label(self):
        return f"{self.f.year - 1}/{self.f.year}" if self.f.season else str(self.f.year)

    def describe(self):
        y, (fy, fw), (ty, tw) = self.f.year, self.weeks[0], self.weeks[-1]
        return f"Epi week {fw} of {fy} to week {tw} of {ty}" if fy != ty else f"Epi weeks {fw}–{tw} of {y}"

    def columns(self):
        return [{"y": y, "w": w} for y, w in self.weeks]


class Context:
    """One report request: the unit, its filters and cases, threshold settings and populations."""

    def __init__(self, unit, get):
        self.unit, self.national = unit, orgunits.is_national(unit)
        self.f = Filters.read(get, unit)
        self.cfg = ThresholdConfig.for_region(unit["name"])
        self.period = Period(self.f, self.cfg)
        self.area_field = "region" if self.national else "district"
        base = region_cases(unit, include_other=False).filter(self.period.q)
        one = {self.area_field: self.f.district}
        self.qs = base.filter(**one) if self.f.district else base
        others = region_cases(unit).filter(self.period.q, other_region=True)
        self.other_n = (others.filter(**one) if self.f.district else others).count()
        subs = SubDistrict.objects.all() if self.national else SubDistrict.objects.filter(region=unit["name"])
        self.subs = {s.id: s for s in subs}

    @property
    def areas(self):
        """The rows: the region's districts (or one), or every region in the national view."""
        names = [n for _, n in self.unit["districts"]]
        return [self.f.district] if self.f.district else names

    def area_of_sub(self, s):
        return s.region if self.national else s.district

    def area_population(self, area):
        pops = [s.population for s in self.subs.values() if self.area_of_sub(s) == area]
        return sum(p for p in pops if p) if pops and all(pops) else None

    def meta(self, kind, title, n):
        place = self.unit["name"].upper() + ("" if self.national else " REGION")
        if self.f.district:
            place = self.f.district.upper() + " DISTRICT – " + place
        return {"kind": kind, "name": KINDS[kind], "title": f"{title} – {self.period.label} – {place}",
                "period": self.period.describe(), "district": self.f.district, "region": unit_label(self.unit),
                "asOf": timezone.localtime().strftime("%d/%m/%Y %H:%M"), "cases": n, "otherRegion": self.other_n,
                "areaLabel": "Region" if self.national else "District", "filters": self.f.__dict__}


# ---------- thresholds ----------
def thresholds(pop, cfg):
    """(alert, epidemic) weekly case counts for a population, and how they were set."""
    if pop and pop > cfg.small_pop_cutoff:
        return (round(float(cfg.alert_rate) * pop / 1e5, 1), round(float(cfg.epidemic_rate) * pop / 1e5, 1), "rate")
    return (cfg.small_pop_alert_cases, cfg.small_pop_epidemic_cases, "cases" if pop else "no population")


def status(cases, limits):
    alert, epidemic, _ = limits
    if not cases:
        return ""
    return "epidemic" if cases >= epidemic else "alert" if cases >= alert else ""


# ---------- building blocks ----------
def totals(qs):
    t = qs.aggregate(c=Count("id"), d=Count("id", filter=DEATH))
    return {"cases": t["c"], "deaths": t["d"], "cfr": pct(t["d"], t["c"])}


def by(qs, *fields):
    """{(field values...): (cases, deaths)}."""
    return {tuple(r[f] for f in fields): (r["c"], r["d"])
            for r in qs.values(*fields).annotate(c=Count("id"), d=Count("id", filter=DEATH)).order_by()}


def age_band():
    whens = [When(age_years__isnull=True, age_months__isnull=False, then=Value("<2"))]
    for name, lo, hi in AGE_BANDS:
        cond = Q(age_years__gte=lo) & (Q(age_years__lt=hi) if hi else Q())
        whens.append(When(cond, then=Value(name)))
    return When_(*whens, default=Value(NOT_GIVEN), output_field=CharField())


def sub_key():
    """The sub-district a case counts in: where the patient lives, else where it was reported."""
    return Coalesce("residence_subdistrict", "reporting_subdistrict", output_field=IntegerField())


def weekly_grid(ctx, keys):
    """{key: {"c": [..per week], "d": [..]}} for keys of (area or sub id, year, week)."""
    n, out = len(ctx.period.weeks), {}
    for (k, y, w), (c, d) in keys.items():
        i = ctx.period.index.get((y, w))
        if i is None:
            continue
        row = out.setdefault(k, {"c": [0] * n, "d": [0] * n})
        row["c"][i] += c
        row["d"][i] += d
    return out


def series_row(label, grid_row, limits, n, **extra):
    c, d = (grid_row or {}).get("c", [0] * n), (grid_row or {}).get("d", [0] * n)
    return {"label": label, "c": c, "d": d, "cases": sum(c), "deaths": sum(d),
            "alert": limits[0] if limits else None, "epidemic": limits[1] if limits else None,
            "basis": limits[2] if limits else None,
            "status": [status(x, limits) for x in c] if limits else [""] * n, **extra}


def sub_rows(ctx):
    """[(area, [sub-district rows]), ...] with the weekly counts of every sub-district, those without cases too."""
    n = len(ctx.period.weeks)
    grid = weekly_grid(ctx, by(ctx.qs.annotate(sd=sub_key()), "sd", "epi_year", "epi_week"))
    no_sub = weekly_grid(ctx, by(ctx.qs.annotate(sd=sub_key()).filter(sd__isnull=True), ctx.area_field, "epi_year", "epi_week"))
    groups = []
    for area in ctx.areas:
        subs = sorted((s for s in ctx.subs.values() if ctx.area_of_sub(s) == area), key=lambda s: s.name.lower())
        rows = [series_row(s.name, grid.get(s.id), thresholds(s.population, ctx.cfg), n, population=s.population, id=s.id)
                for s in subs]
        if area in no_sub:
            rows.append(series_row(NOT_GIVEN, no_sub[area], None, n, population=None, id=None))
        groups.append((area, rows))
    # Every case is counted once: sub-districts outside the rows (a patient reported in the chosen district who
    # lives in another one) and districts not in the org unit list go under Others.
    shown = {r["id"] for _, rows in groups for r in rows if r["id"]}
    known = set(ctx.areas)
    others = [series_row(f"{ctx.subs[k].name} ({ctx.area_of_sub(ctx.subs[k])})" if k in ctx.subs else NOT_GIVEN, v, None, n,
                         population=None, id=None) for k, v in grid.items() if k is not None and k not in shown]
    others += [series_row(k or NOT_GIVEN, v, None, n, population=None, id=None) for k, v in no_sub.items() if k not in known]
    if others:
        groups.append(("Others", sorted(others, key=lambda r: str(r["label"]))))
    return groups


def area_label_rows(ctx):
    """[(area, (cases, deaths))] for every area, then Others (districts not in the org unit list) when there are any."""
    counts = by(ctx.qs, ctx.area_field)
    rows = [(a, counts.get((a,), (0, 0))) for a in ctx.areas]
    others = [v for (k,), v in counts.items() if k not in set(ctx.areas)]
    if others:
        rows.append(("Others", (sum(c for c, _ in others), sum(d for _, d in others))))
    return rows


def count_table(qs, field, list_name, total):
    """[{label, n, pct}] for a coded field: every code with cases, then Missing."""
    counts = {r[field]: r["n"] for r in qs.values(field).annotate(n=Count("id")).order_by()}
    rows = [{"code": c, "label": f"{c}-{t}", "n": counts.get(c, 0), "pct": pct(counts.get(c, 0), total)}
            for c, t in ch.LISTS[list_name]]
    rows.append({"code": "", "label": "Missing", "n": counts.get("", 0), "pct": pct(counts.get("", 0), total)})
    return {"rows": rows, "total": total}


# ---------- the reports ----------
def weekly(ctx):
    n, groups, out = len(ctx.period.weeks), sub_rows(ctx), []
    for area, rows in groups:
        tot_c = [sum(r["c"][i] for r in rows) for i in range(n)]
        tot_d = [sum(r["d"][i] for r in rows) for i in range(n)]
        out.append({"area": area, "rows": rows, "total": {"c": tot_c, "d": tot_d, "cases": sum(tot_c), "deaths": sum(tot_d)}})
    gc = [sum(g["total"]["c"][i] for g in out) for i in range(n)]
    gd = [sum(g["total"]["d"][i] for g in out) for i in range(n)]
    t = totals(ctx.qs)
    return {**ctx.meta("weekly", "MENINGITIS CASES AND DEATHS BY SUB-DISTRICT AND EPI WEEK", t["cases"]),
            "weeks": ctx.period.columns(), "groups": out, "total": {"c": gc, "d": gd, "cases": sum(gc), "deaths": sum(gd)},
            "cfg": cfg_dict(ctx.cfg)}


def district(ctx):
    n = len(ctx.period.weeks)
    grid = weekly_grid(ctx, by(ctx.qs, ctx.area_field, "epi_year", "epi_week"))
    rows = [series_row(a, grid.get(a), thresholds(ctx.area_population(a), ctx.cfg), n, population=ctx.area_population(a))
            for a in ctx.areas]
    stray = [k for k in grid if k not in set(ctx.areas)]
    if stray:
        oc = [sum(grid[k]["c"][i] for k in stray) for i in range(n)]
        od = [sum(grid[k]["d"][i] for k in stray) for i in range(n)]
        rows.append(series_row("Others", {"c": oc, "d": od}, None, n, population=None))
    tc = [sum(r["c"][i] for r in rows) for i in range(n)]
    td = [sum(r["d"][i] for r in rows) for i in range(n)]
    area = "REGION" if ctx.national else "DISTRICT"
    return {**ctx.meta("district", f"MENINGITIS CASES AND DEATHS BY {area}", sum(tc)), "weeks": ctx.period.columns(),
            "rows": rows, "total": {"c": tc, "d": td, "cases": sum(tc), "deaths": sum(td)}}


def regional(ctx):
    t = totals(ctx.qs)
    areas = [{"label": a, "cases": c, "deaths": d, "cfr": pct(d, c)} for a, (c, d) in area_label_rows(ctx)]
    ages = by(ctx.qs.annotate(band=age_band()), "band")
    age_rows = [{"label": name, "cases": ages.get((name,), (0, 0))[0], "deaths": ages.get((name,), (0, 0))[1],
                 "cfr": pct(ages.get((name,), (0, 0))[1], ages.get((name,), (0, 0))[0])} for name, _, _ in AGE_BANDS]
    if (NOT_GIVEN,) in ages:
        c, d = ages[(NOT_GIVEN,)]
        age_rows.append({"label": "Age not given", "cases": c, "deaths": d, "cfr": pct(d, c)})
    sexes = by(ctx.qs, "sex")
    sex_rows = [{"label": t_, "cases": sexes.get((c_,), (0, 0))[0], "deaths": sexes.get((c_,), (0, 0))[1]}
                for c_, t_ in ch.SEX] + [{"label": "Missing", "cases": sexes.get(("",), (0, 0))[0], "deaths": sexes.get(("",), (0, 0))[1]}]
    path = by(ctx.qs, "final_result")
    path_rows = [{"label": f"{c_}-{t_}", "cases": path.get((c_,), (0, 0))[0], "deaths": path.get((c_,), (0, 0))[1]}
                 for c_, t_ in ch.PATHOGEN if path.get((c_,))]
    if path.get(("",)):
        path_rows.append({"label": "No result", "cases": path[("",)][0], "deaths": path[("",)][1]})
    subs = []
    for area, rows in sub_rows(ctx):
        for r in rows:
            if r["cases"] or r["id"]:
                subs.append({"area": area, "label": r["label"], "cases": r["cases"], "deaths": r["deaths"],
                             "cfr": pct(r["deaths"], r["cases"])})
    return {**ctx.meta("regional", "MENINGITIS SUMMARY", t["cases"]), "total": t, "areas": areas, "ages": age_rows,
            "sexes": sex_rows, "pathogens": path_rows, "subdistricts": subs}


def epicurve(ctx):
    n = len(ctx.period.weeks)
    raw = by(ctx.qs, "final_classification", "epi_year", "epi_week")
    series = []
    for code, name in ch.CLASSIFICATION + [("", "Not classified")]:
        vals = [0] * n
        for (c, y, w), (k, _) in raw.items():
            if c == code and (y, w) in ctx.period.index:
                vals[ctx.period.index[(y, w)]] += k
        series.append({"code": code, "label": name, "values": vals, "total": sum(vals)})
    total = sum(s["total"] for s in series)
    return {**ctx.meta("epicurve", "MENINGITIS EPI CURVE: CASES BY EPI WEEK AND FINAL CLASSIFICATION", total),
            "weeks": ctx.period.columns(), "series": series}


def vaccination(ctx):
    n = ctx.qs.count()
    spec = ctx.qs.filter(specimen_collected=ch.YES)
    n_spec = spec.count()
    with_result = spec.exclude(final_result__in=["", "15"]).count()
    confirmed = ctx.qs.filter(final_classification=ch.CONFIRMED).count()
    vacc = ctx.qs.filter(vaccinated=ch.YES).count()
    known_vacc = ctx.qs.filter(vaccinated__in=[ch.YES, ch.NO]).count()
    t = totals(ctx.qs)
    indicators = [
        {"label": "Case fatality rate", "n": t["deaths"], "of": n, "pct": t["cfr"], "note": "deaths of all cases"},
        {"label": "Specimens collected", "n": n_spec, "of": n, "pct": pct(n_spec, n), "note": "of all cases"},
        {"label": "With a final lab result", "n": with_result, "of": n_spec, "pct": pct(with_result, n_spec), "note": "of specimens collected"},
        {"label": "Confirmed", "n": confirmed, "of": n, "pct": pct(confirmed, n), "note": "of all cases"},
        {"label": "Vaccinated", "n": vacc, "of": known_vacc, "pct": pct(vacc, known_vacc), "note": "of cases with a known status"},
    ]
    key_fields = [("sex", "Sex"), ("date_onset", "Date of onset"), ("outcome", "Outcome"), ("vaccinated", "Vaccinated?"),
                  ("specimen_collected", "Specimen collected"), ("final_classification", "Final classification"),
                  ("health_facility", "Health facility"), ("community", "Community")]
    completeness = []
    for f, label in key_fields:
        missing = ctx.qs.filter(Q(**{f + "__isnull": True}) | Q(**{f: ""}) if f != "date_onset" else Q(date_onset__isnull=True)).count()
        completeness.append({"label": label, "missing": missing, "pct": pct(n - missing, n)})
    age_missing = ctx.qs.filter(age_years__isnull=True, age_months__isnull=True).count()
    completeness.insert(1, {"label": "Age", "missing": age_missing, "pct": pct(n - age_missing, n)})
    sub_missing = ctx.qs.filter(residence_subdistrict__isnull=True, reporting_subdistrict__isnull=True).count()
    completeness.append({"label": "Sub-district", "missing": sub_missing, "pct": pct(n - sub_missing, n)})
    return {**ctx.meta("vaccination", "MENINGITIS VACCINATION STATUS AND INDICATORS", n), "indicators": indicators,
            "tables": [
                {"title": "Any immunisation", **count_table(ctx.qs, "vaccinated", "yesno", n)},
                {"title": "Vaccine 1", **count_table(ctx.qs, "vaccine_1", "vaccine", n)},
                {"title": "Vaccine 2", **count_table(ctx.qs, "vaccine_2", "vaccine", n)},
                {"title": "PCV vaccination status", **count_table(ctx.qs, "pcv", "pcv", n)},
                {"title": "Outcome", **count_table(ctx.qs, "outcome", "outcome", n)},
                {"title": "Specimen collected", **count_table(ctx.qs, "specimen_collected", "yesno", n)},
            ], "completeness": completeness}


def laboratory(ctx):
    n = ctx.qs.count()
    tables = [{"title": t, **count_table(ctx.qs, f, l, n)} for t, f, l in [
        ("Gram stain", "gram", "gram"), ("Rapid test (TDR)", "rapid_test", "rapid"), ("Latex", "latex", "latex"),
        ("Culture", "culture", "pathogen"), ("PCR", "pcr", "pathogen"), ("Final lab result", "final_result", "pathogen")]]
    for t in tables:  # keep the long lists short: codes no case has are left out
        t["rows"] = [r for r in t["rows"] if r["n"] or r["label"] == "Missing"]
    path = {r["final_result"]: r["n"] for r in ctx.qs.filter(final_result__in=ch.BACTERIA).values("final_result").annotate(n=Count("id")).order_by()}
    pathogens = [{"label": t_, "n": path[c_]} for c_, t_ in ch.PATHOGEN if path.get(c_)]
    return {**ctx.meta("laboratory", "MENINGITIS LABORATORY RESULTS", n), "tables": tables, "pathogens": pathogens,
            "specimens": ctx.qs.filter(specimen_collected=ch.YES).count()}


def threshold_charts(ctx):
    charts = []
    for area, rows in sub_rows(ctx):
        for r in rows:
            if r["id"] is None:
                continue
            charts.append({**r, "area": area,
                           "title": f"MENINGITIS THRESHOLD FOR {r['label'].upper()} SUB-DISTRICT – {ctx.period.label} – {ctx.unit['name'].upper()}"})
    n = totals(ctx.qs)["cases"]
    return {**ctx.meta("thresholds", "MENINGITIS THRESHOLDS BY SUB-DISTRICT", n), "weeks": ctx.period.columns(),
            "charts": charts, "cfg": cfg_dict(ctx.cfg)}


def latest_week(ctx):
    """The latest complete week of the period (the week before this one), as weekly surveillance reports it."""
    last = (timezone.localdate() - timedelta(days=7)).isocalendar()
    done = [w for w in ctx.period.weeks if w <= (last[0], last[1])]
    return (done or ctx.period.weeks[:1])[-1]


def dashboard(ctx):
    t = totals(ctx.qs)
    confirmed = ctx.qs.filter(final_classification=ch.CONFIRMED).count()
    wk = latest_week(ctx)
    i = ctx.period.index[wk]
    d = district(ctx)
    subs = [(area, r) for area, rows in sub_rows(ctx) for r in rows if r["id"] is not None]
    in_alert = [{"area": a, "label": r["label"], "cases": r["c"][i]} for a, r in subs if r["status"][i] == "alert"]
    in_epidemic = [{"area": a, "label": r["label"], "cases": r["c"][i]} for a, r in subs if r["status"][i] == "epidemic"]
    week_cases = sum(r["c"][i] for r in d["rows"])
    areas = [{"label": r["label"], "cases": r["cases"], "deaths": r["deaths"], "cfr": pct(r["deaths"], r["cases"]),
              "week": r["c"][i], "status": r["status"][i], "population": r.get("population")} for r in d["rows"]]
    return {**ctx.meta("dashboard", "MENINGITIS SITUATION", t["cases"]), "total": t,
            "confirmedPct": pct(confirmed, t["cases"]), "confirmed": confirmed, "week": {"y": wk[0], "w": wk[1]},
            "weekCases": week_cases, "alert": in_alert, "epidemic": in_epidemic, "areas": areas,
            "curve": epicurve(ctx)["series"], "weeks": ctx.period.columns()}


BUILDERS = {"dashboard": dashboard, "weekly": weekly, "district": district, "regional": regional, "epicurve": epicurve,
            "vaccination": vaccination, "laboratory": laboratory, "thresholds": threshold_charts}


def build(unit, get):
    kind = get.get("kind", "dashboard")
    if kind not in BUILDERS:
        raise ValueError("Choose a report.")
    return BUILDERS[kind](Context(unit, get))


def cfg_dict(cfg):
    return {"alertRate": float(cfg.alert_rate), "epidemicRate": float(cfg.epidemic_rate), "cutoff": cfg.small_pop_cutoff,
            "alertCases": cfg.small_pop_alert_cases, "epidemicCases": cfg.small_pop_epidemic_cases,
            "seasonStart": cfg.season_start_week, "saved": cfg.pk is not None}
