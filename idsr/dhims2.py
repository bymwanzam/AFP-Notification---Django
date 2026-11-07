"""Fetch the weekly IDSR figures from DHIMS2 (Ghana's DHIS2) into the Weekly IDSR store.

Sign-in is a DHIS2 personal access token (DHIMS2 → your profile → Personal access tokens). The token is sent
only to the DHIMS2 address set here and never to the page. It is kept with the sign-in (Django's server-side
session, so every process of the app sees it, until sign-out), and written to disk only when "remember" is ticked: then to config_file(), in PRIVATE_MEDIA, which is never served.

Figures come from the DHIMS2 analytics API, summed by district and epi week, so they are as fresh as the last
analytics run on DHIMS2 (usually overnight). Which DHIMS2 data element fills which IDSR column is a mapping,
suggested from the names and kept per data set in config_file().
"""
import contextvars
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

from core import orgunits

from .store import COLS, DISEASES, HEAD, check_week

DEFAULT_URL = "https://dhims.chimgh.org/dhims"
TIMEOUT = 90
# DHIMS2 sits behind Cloudflare, which refuses Python's default User-Agent ("Python-urllib", error 1010), so the
# app names itself.
USER_AGENT = "GHS-Surveillance/1.0"
# Every failed call is written to django-errors.log (path, status, DHIMS2's message and how long it took; never the
# token), so a failed fetch can be looked into afterwards.
log = logging.getLogger("idsr.dhims2")
UID = re.compile(r"^[A-Za-z][A-Za-z0-9]{10}$")
# The token of the request being served, from the signed-in user's server-side session: the hosting server runs the
# app in several processes, so a token held in one process's memory is missing in the next request's process.
_request_token = contextvars.ContextVar("dhims2_token", default=None)
SESSION_KEY = "dhims2_token"


def use_session(session):
    """Called for each DHIMS2 request: the token this sign-in connected with, if any."""
    _request_token.set(session.get(SESSION_KEY))

# Words in DHIMS2 data element (and category option) names that point to each IDSR disease and measure.
DISEASE_WORDS = {
    "dengue": r"dengue", "yf": r"yellow fever|\byf\b",  # before AHF: dengue / yellow fever can say haemorrhagic
    "afp": r"\bafp\b|flaccid|polio", "ahf": r"ha?emorrhagic|\bvhf\b|\bahf\b", "aefi": r"\baefi\b|adverse event",
    "anthrax": r"anthrax", "cholera": r"cholera",
    "shigella": r"shigell|dysenter|diarrho?ea with blood|bloody diarrho?ea", "guinea": r"guinea worm|dracuncul",
    "ili": r"influenza.like|\bili\b", "matdeath": r"maternal (death|mortality)", "measles": r"measles",
    "mening": r"mening|\bcsm\b", "nnt": r"neonatal tetanus|\bnnt\b", "plague": r"plague", "rabies": r"rabies|dog bite",
    "sari": r"\bsari\b|severe acute resp", "mpox": r"\bmpox|monkey ?pox|smallpox",
    "awd_u5": r"(watery diarrho?ea|\bawd\b).*(<\s*5|under\s*5|\bu5\b|0\s*-\s*4)",
    "awd_o5": r"(watery diarrho?ea|\bawd\b).*(>\s*5|5\s*\+|5\s*(years)? and (over|above)|over\s*5|above\s*5)",
    "bu": r"buruli", "covid": r"covid", "zika": r"zika", "pheic": r"\bpheic\b|public health event",
}
MEASURE_WORDS = [("Rumour", r"rumou?r"), ("D", r"death|died|dead|fatal"), ("LC", r"\blab|confirm|positive"),
                 ("CS", r"case|suspect")]


# ---------- settings ----------
def config_file():
    return settings.PRIVATE_MEDIA / "dhims2.json"


def load():
    try:
        return json.loads(config_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(cfg):
    config_file().parent.mkdir(parents=True, exist_ok=True)
    config_file().write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def token():
    """This sign-in's token, else the one remembered (ticked "Remember") for everyone on this app."""
    return _request_token.get() or load().get("token")


def public_config():
    """The settings the page may see: never the token itself."""
    cfg, t = load(), token()
    return {"url": cfg.get("url") or DEFAULT_URL, "hasToken": bool(t), "tokenEnd": t[-4:] if t else "",
            "remembered": bool(cfg.get("token")), "user": cfg.get("user", "") if t else "",
            "dataSet": cfg.get("dataSet", ""), "configFile": "private_media/" + config_file().name}


def clean_url(url):
    url = str(url or "").strip().rstrip("/")
    url = re.sub(r"/(api|dhis-web-[\w-]+)(/.*)?$", "", url)  # pasted from a browser tab or an API link
    if not re.match(r"^https?://[^\s/]+", url):
        raise ValueError("Enter the DHIMS2 address, starting with https://")
    return url


# ---------- talking to DHIMS2 ----------
class NotFound(ValueError):
    """DHIMS2 answered 404: the thing asked for (an org unit id, a data set) does not exist there."""


def call(path, params=None, url=None, tok=None):
    base, tok = clean_url(url or load().get("url") or DEFAULT_URL), tok or token()
    if not tok:
        log.error("DHIMS2 %s: no token (not connected in this run of the app, and not remembered)", path)
        raise ValueError("Connect to DHIMS2 with your access token first.")
    query = urllib.parse.urlencode(params or {}, doseq=True, safe=":;.,[]")
    req = urllib.request.Request(f"{base}/api/{path}" + (f"?{query}" if query else ""),
                                 headers={"Authorization": f"ApiToken {tok}", "Accept": "application/json",
                                          "User-Agent": USER_AGENT})
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            detail = json.loads(raw).get("message", "")
        except Exception:
            detail = ""
        log.error("DHIMS2 %s -> HTTP %s after %.1fs: %s", f"{base}/api/{path}?{query}"[:600], e.code,
                  time.monotonic() - started, detail or raw[:200].decode(errors="replace"))
        if b"error code: 10" in raw[:200]:  # Cloudflare refused the request before it reached DHIMS2
            raise ValueError(f"The DHIMS2 firewall (Cloudflare) refused the request ({raw[:40].decode(errors='replace').strip()}). "
                             "Try again later, or ask the DHIMS2 team to allow this app.") from None
        if e.code == 400 and re.search(r"token|checksum", detail, re.I):
            raise ValueError("DHIMS2 did not recognise this token. Copy it again in full (it starts with d2pat_) and connect.") from None
        if e.code == 404:
            # the address is right (DHIMS2 answered); what was asked for is not there
            raise NotFound(f"DHIMS2: {detail}" if detail else f"DHIMS2 has nothing at /api/{path.split('?')[0]}. "
                           "If this keeps happening, check the DHIMS2 address.") from None
        raise ValueError({
            401: "DHIMS2 did not accept the token. It may have expired or been revoked: create a new one and connect again.",
            403: "Your DHIMS2 account is not allowed to read this. " + detail,
        }.get(e.code) or f"DHIMS2 answered with error {e.code}. {detail}".strip()) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        took = time.monotonic() - started
        log.error("DHIMS2 %s -> no answer after %.1fs: %s", f"{base}/api/{path}?{query}"[:600], took, reason)
        if took >= TIMEOUT - 1 or "timed out" in str(reason).lower():
            raise ValueError(f"DHIMS2 took longer than {TIMEOUT} seconds to answer. Fetch fewer weeks at a time "
                             "(for example one or four), or try again later when DHIMS2 is less busy.") from None
        raise ValueError(f"Could not reach DHIMS2 at {base} ({reason}). Check the internet connection and the address.") from None
    if body.lstrip()[:1] == b"<":
        log.error("DHIMS2 %s -> a web page instead of data", f"{base}/api/{path}"[:300])
        raise ValueError("DHIMS2 sent back a web page instead of data (often its login page). Check the address and the token.")
    return json.loads(body)


def connect(url, tok, remember):
    url, tok = clean_url(url), str(tok or "").strip() or token()
    if not tok:
        raise ValueError("Paste your DHIMS2 access token.")
    me = call("me", {"fields": "displayName,username"}, url, tok)
    cfg = load()
    cfg.update(url=url, user=me.get("displayName") or me.get("username") or "")
    if remember:
        cfg["token"] = tok
    else:
        cfg.pop("token", None)
    save(cfg)
    _request_token.set(tok)
    return public_config()


def forget():
    _request_token.set(None)
    cfg = load()
    cfg.pop("token", None)
    save(cfg)
    return public_config()


def data_sets():
    """Weekly data sets first, IDSR ones at the top."""
    sets = call("dataSets", {"fields": "id,displayName,periodType", "paging": "false"}).get("dataSets", [])
    rank = lambda d: (d.get("periodType") != "Weekly", "idsr" not in d["displayName"].lower(), d["displayName"].lower())
    return [{"id": d["id"], "name": d["displayName"], "period": d.get("periodType", "")} for d in sorted(sets, key=rank)]


def elements(ds):
    if not UID.match(ds or ""):
        raise ValueError("Choose a DHIMS2 data set.")
    fields = "id,displayName,periodType,dataSetElements[dataElement[id,displayName,categoryCombo[categoryOptionCombos[id,displayName]]]]"
    d = call(f"dataSets/{ds}", {"fields": fields})
    out = []
    for x in d.get("dataSetElements", []):
        de = x.get("dataElement") or {}
        combos = [{"id": c["id"], "name": c["displayName"]} for c in (de.get("categoryCombo") or {}).get("categoryOptionCombos", [])
                  if c.get("displayName", "").lower() != "default"]
        out.append({"id": de["id"], "name": de.get("displayName", de["id"]), "combos": sorted(combos, key=lambda c: c["name"])})
    out.sort(key=lambda e: e["name"].lower())
    cfg = load()
    cfg["dataSet"] = ds
    save(cfg)
    saved = cfg.get("mappings", {}).get(ds)
    return {"name": d.get("displayName", ds), "period": d.get("periodType", ""), "elements": out,
            "mapping": saved if saved is not None else suggest(out), "suggested": saved is None}


# ---------- which data element fills which IDSR column ----------
def classify(name):
    """(disease key, measure or None) that a DHIMS2 name points to, or (None, None)."""
    n = name.lower()
    disease = next((k for k, rx in DISEASE_WORDS.items() if re.search(rx, n)), None)
    measure = next((m for m, rx in MEASURE_WORDS if re.search(rx, n)), None)
    return disease, measure


def suggest(els):
    """{column: 'element' or 'element.combo'} guessed from the names, for the user to check."""
    measures = {d["key"]: d["measures"] for d in DISEASES}
    found = {}

    def put(disease, measure, item):
        col = f"{disease}.{measure or ('D' if measures[disease] == ['D'] else 'CS')}"
        if col in COLS:
            found.setdefault(col, item)

    for e in els:
        disease, measure = classify(e["name"])
        # One element whose category options are different columns (Cases / Deaths, or AWD < 5 / 5+): map each
        # option. Options that are all the same column (age groups of "AFP cases") use the element's total.
        by_combo = [(c, *classify(e["name"] + " " + c["name"])) for c in e["combos"]]
        if len({(d, m or "CS") for _, d, m in by_combo if d}) > 1:
            for c, d, m in by_combo:
                if d:
                    put(d, m, f"{e['id']}.{c['id']}")
        elif disease:
            put(disease, measure, e["id"])
    return found


def save_mapping(ds, mapping):
    if not UID.match(ds or ""):
        raise ValueError("Choose a DHIMS2 data set.")
    clean = {}
    for col, item in (mapping or {}).items():
        if col not in COLS or not item:
            continue
        if not all(UID.match(p) for p in str(item).split(".")) or str(item).count(".") > 1:
            raise ValueError(f"{HEAD[col]}: not a DHIMS2 data element.")
        clean[col] = str(item)
    cfg = load()
    cfg.setdefault("mappings", {})[ds] = clean
    cfg["dataSet"] = ds
    save(cfg)
    return clean


# ---------- org units: DHIMS2's own ids ----------
def region_id(unit):
    """(DHIMS2 id, level) of a region. The ids in core/data/ghana-org-units.json come from a DHIS2 export and may not
    be DHIMS2's (Upper East's was not): an id DHIMS2 does not know is looked up by the region's name instead, and the
    one found is remembered in config_file()."""
    cached = load().get("orgUnitIds", {}).get(unit["name"])
    if isinstance(cached, list) and len(cached) == 2:  # [id, level], found on DHIMS2 before
        return cached[0], int(cached[1])
    uid = unit.get("id")
    if uid:
        try:
            level = int(call(f"organisationUnits/{uid}", {"fields": "id,level"})["level"])
            remember_unit(unit["name"], uid, level)
            return uid, level
        except NotFound:
            pass
    found = call("organisationUnits", {"filter": f"name:ilike:{unit['name']}", "fields": "id,name,level", "paging": "false"})
    want = orgunits.bare(unit["name"])
    matches = [o for o in found.get("organisationUnits", [])
               if orgunits.bare(re.sub(r"(?i)\s*region$", "", o.get("name", ""))) == want and o.get("level")]
    if not matches:
        raise ValueError(f"DHIMS2 has no org unit called {unit['name']} (looked up by name, as its id "
                         f"{unit.get('id') or '(none)'} is not on DHIMS2). Ask the DHIMS2 team for the region's id.")
    best = min(matches, key=lambda o: o["level"])  # the region itself, not a district or facility of the same name
    remember_unit(unit["name"], best["id"], best["level"])
    log.error("DHIMS2 org unit for %s: id %s was not found, using %s (%s, level %s) found by name",
              unit["name"], unit.get("id"), best["id"], best.get("name"), best["level"])
    return best["id"], int(best["level"])


def remember_unit(name, uid, level):
    cfg = load()
    cfg.setdefault("orgUnitIds", {})[name] = [uid, int(level)]
    save(cfg)



# ---------- fetching ----------
def analytics(dx, periods, ou):
    """[(item, period, org unit id, value)] and org unit names, asking for a few items at a time to keep URLs short."""
    rows, names = [], {}
    for i in range(0, len(dx), 30):
        d = call("analytics", {"dimension": [f"dx:{';'.join(dx[i:i + 30])}", f"pe:{';'.join(periods)}", f"ou:{ou}"],
                               "skipRounding": "true", "displayProperty": "NAME"})
        idx = {h["name"]: k for k, h in enumerate(d.get("headers", []))}
        for r in d.get("rows", []):
            try:
                rows.append((r[idx["dx"]], r[idx["pe"]], r[idx["ou"]], float(r[idx["value"]])))
            except (KeyError, ValueError, IndexError):
                continue
        names.update({k: v.get("name", k) for k, v in (d.get("metaData") or {}).get("items", {}).items()})
    return rows, names


def fetch(store, ds, mapping, year, first, last):
    """Weeks first..last of `year` from DHIMS2, as an import plan for the store (nothing is saved here)."""
    mapping = save_mapping(ds, mapping)
    if not mapping:
        raise ValueError("Map at least one IDSR column to a DHIMS2 data element first.")
    y, w1 = check_week(year, first)
    _, w2 = check_week(year, last)
    if w2 < w1:
        w1, w2 = w2, w1
    if w2 - w1 > 52:
        raise ValueError("Fetch up to one year of weeks at a time.")
    periods = [f"{y}W{w}" for w in range(w1, w2 + 1)]
    if getattr(store, "national", False):
        # Ghana: the figures of each region (DHIMS2 adds up its districts), one row per region.
        unit = orgunits.national_unit()
        ids = {r["code"]: region_id(r)[0] for r in orgunits.ORG_UNITS}
        unit = unit | {"ids": ids}
        ou = ";".join(ids.values())
    else:
        unit = orgunits.region_of(store.region)
        if not unit:
            raise ValueError(f"{store.region or 'This region'} is not in the org unit list.")
        uid, level = region_id(unit)
        ou = f"{uid};LEVEL-{level + 1}"

    items = sorted(set(mapping.values()))
    rows, names = analytics(items, periods, ou)
    problems, notes = [], []
    try:  # DHIMS2 reporting: expected, received and on-time reports, for completeness and timeliness
        rep = [f"{ds}.{m}" for m in ("EXPECTED_REPORTS", "ACTUAL_REPORTS", "ACTUAL_REPORTS_ON_TIME")]
        rep_rows, rep_names = analytics(rep, periods, ou)
        names.update(rep_names)
    except ValueError as e:
        rep_rows = []
        notes.append(f"Reporting completeness could not be read from DHIMS2: {e}")

    by_id = {i: c for c, i in unit.get("ids", {}).items() if i}
    known = {c for c, _ in store.districts}
    codes, unmatched = {}, set()

    def code_of(ou_id):
        if ou_id not in codes:
            c = by_id.get(ou_id)
            codes[ou_id] = c if c in known else store.district_code(names.get(ou_id, ""))
            if not codes[ou_id]:
                unmatched.add(names.get(ou_id, ou_id))
        return codes[ou_id]

    week_of = {p: int(p.split("W")[1]) for p in periods}
    incoming, reported = {}, {}
    for item, pe, ou_id, value in rows:
        code = code_of(ou_id)
        if not code or pe not in week_of:
            continue
        vals = incoming.setdefault((y, week_of[pe]), {"meta": {}, "counts": {}})["counts"].setdefault(code, {})
        for col, it in mapping.items():
            if it == item:
                vals[col] = vals.get(col, 0) + value
        reported.setdefault(week_of[pe], set()).add(code)
    totals = {}
    for item, pe, ou_id, value in rep_rows:
        if pe not in week_of:
            continue
        kind = item.rsplit(".", 1)[1]
        t = totals.setdefault(week_of[pe], {})
        t[kind] = t.get(kind, 0) + value
        if kind == "ACTUAL_REPORTS" and value > 0 and (code := code_of(ou_id)):
            reported.setdefault(week_of[pe], set()).add(code)

    # A district that sent its report has 0 for every mapped column DHIMS2 left empty (DHIS2 does not store zeros).
    for w in range(w1, w2 + 1):
        t, sent = totals.get(w, {}), reported.get(w, set())
        if not sent and not t.get("ACTUAL_REPORTS"):
            notes.append(f"Week {w:03d}: no data in DHIMS2 yet.")
            incoming.pop((y, w), None)
            continue
        week = incoming.setdefault((y, w), {"meta": {}, "counts": {}})
        for code in sent:
            vals = week["counts"].setdefault(code, {})
            for col in mapping:
                vals[col] = round(vals.get(col, 0))
        if t.get("EXPECTED_REPORTS"):  # DHIS2 leaves out zero rows: no on-time row means none were on time
            week["meta"] = {"expected": round(t["EXPECTED_REPORTS"]), "received": round(t.get("ACTUAL_REPORTS", 0)),
                            "ontime": round(t.get("ACTUAL_REPORTS_ON_TIME", 0))}
    if unmatched:
        problems.append("DHIMS2 org units not matched to a " + ("region" if getattr(store, "national", False) else "district")
                        + " (their figures are left out): " + ", ".join(sorted(unmatched)))
    missing = [HEAD[c] for c in COLS if c not in mapping]
    if missing:
        notes.append(f"{len(missing)} IDSR columns are not mapped to DHIMS2 and are left as they are.")
    plan = store.plan_incoming(incoming, problems, notes)
    plan["source"] = {"weeks": [w1, w2], "year": y, "dataSet": ds}
    return plan
