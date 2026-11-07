"""AFP 60-day follow-up reminders by SMS to district officers.

The rules are the AFP page's (afp/static/afp/js/dashboard.js): the follow-up visit is due 60 days after onset;
a case is "due soon" in the last 7 days before that, and "past due" after it, until its Outcome is "FUP done".

- Before the due date: one reminder when a case enters its last REMINDER_SOON_DAYS days.
- Overdue: one reminder on the first day overdue, then one every REMINDER_REPEAT_DAYS days until follow-up is done.

Each officer gets one SMS per run listing their cases (EPID numbers and dates only, never patient names). The log
keeps each case, stage and phone to one SMS; failed sends are tried again on the next run.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.conf import settings
from django.utils import timezone

from afp import cases as afp_cases
from core import orgunits

from . import letsfish
from .models import DistrictContact, ReminderLog

FUP = 60
MAX_LISTED = 6  # cases named in one SMS; the rest are counted


def norm(v):
    return str(v or "").strip().lower()


@dataclass
class Due:
    epid: str
    region: str
    district: str
    onset: date
    due: date
    days_left: int  # negative once overdue
    stage: str

    @property
    def overdue(self):
        return self.days_left < 0


def stage_of(days_left):
    """'soon', 'past-1', 'past-2', ... or None (not yet in the window)."""
    soon, repeat = settings.REMINDER_SOON_DAYS, max(1, settings.REMINDER_REPEAT_DAYS)
    if 0 <= days_left <= soon:
        return "soon"
    if days_left < 0:
        return f"past-{(-days_left - 1) // repeat + 1}"
    return None


def due_cases(today=None, region=None):
    """The register's cases due soon or overdue today, for one region or all."""
    today = today or timezone.localdate()
    out = []
    for c in afp_cases.load_cases(settings.AFP_REGISTER):
        if norm(c.get("outcome")) == "fup done" or not c.get("onset") or not c.get("epid"):
            continue
        try:
            onset = date.fromisoformat(str(c["onset"])[:10])
        except ValueError:
            continue
        due = onset + timedelta(days=FUP)
        left = (due - today).days
        stage = stage_of(left)
        if not stage or onset > today:
            continue
        r, d = orgunits.district_region(c.get("district"))
        reg = (r or orgunits.case_region(c.get("district")))["name"]
        if region and reg != region:
            continue
        out.append(Due(str(c["epid"]).strip().upper(), reg, d[1] if d else str(c.get("district") or ""), onset, due, left, stage))
    return sorted(out, key=lambda x: x.days_left)


@dataclass
class Message:
    contact: DistrictContact
    cases: list = field(default_factory=list)
    text: str = ""


def compose(contact, items, today):
    place = contact.district or f"{contact.region} Region"
    soon = [x for x in items if not x.overdue]
    late = [x for x in items if x.overdue]
    lines, listed = [f"GHS AFP 60-day follow-up reminder, {place}."], 0

    def add(title, group, fmt):
        nonlocal listed
        if not group:
            return
        lines.append(title)
        for x in group:
            if listed >= MAX_LISTED:
                break
            lines.append(fmt(x))
            listed += 1

    add(f"OVERDUE ({len(late)}):", late, lambda x: f"{x.epid} due {x.due:%d/%m}, {-x.days_left} d late")
    add(f"DUE SOON ({len(soon)}):", soon, lambda x: f"{x.epid} due {x.due:%d/%m}" + (" (today)" if x.days_left == 0 else f" (in {x.days_left} d)"))
    if len(items) > listed:
        lines.append(f"+{len(items) - listed} more on the AFP page.")
    lines.append("Please do the follow-up visit and update the register.")
    return "\n".join(lines)


def plan(today=None, region=None):
    """[Message] for every active contact with cases not yet sent at their current stage."""
    today = today or timezone.localdate()
    due = due_cases(today, region)
    contacts = DistrictContact.objects.filter(active=True)
    if region:
        contacts = contacts.filter(region=region)
    sent = {(l.epid, l.stage, l.phone) for l in ReminderLog.objects.filter(ok=True, epid__in=[d.epid for d in due])}
    by_place = defaultdict(list)
    for d in due:
        by_place[(d.region, orgunits.bare(d.district))].append(d)
        by_place[(d.region, "")].append(d)
    out = []
    for c in contacts:
        items = [d for d in by_place.get((c.region, orgunits.bare(c.district) if c.district else ""), [])
                 if (d.epid, d.stage, c.phone) not in sent]
        if items:
            out.append(Message(c, items, compose(c, items, today)))
    return out


def run(today=None, region=None, dry_run=False, user=None):
    """Send today's reminders. Returns [{to, name, place, cases, text, ok, error}] (nothing sent when dry_run)."""
    results = []
    for m in plan(today, region):
        row = {"to": m.contact.phone, "name": m.contact.name, "place": m.contact.district or f"{m.contact.region} Region",
               "cases": [{"epid": d.epid, "stage": d.stage, "due": d.due, "daysLeft": d.days_left} for d in m.cases],
               "text": m.text, "ok": None, "error": ""}
        if not dry_run:
            try:
                answer = letsfish.send([m.contact.phone], m.text)
                ref = (answer[0] or {}).get("reference", "") if answer else ""
                row["ok"] = True
            except letsfish.SmsError as e:
                ref, row["ok"], row["error"] = "", False, str(e)
            ReminderLog.objects.bulk_create([ReminderLog(
                epid=d.epid, stage=d.stage, region=d.region, district=d.district, phone=m.contact.phone,
                contact=m.contact.name, ok=row["ok"], reference=ref[:60], error=row["error"][:300], sent_by=user) for d in m.cases])
        results.append(row)
        if row["ok"] is False and any(w in row["error"] for w in ("balance", "App ID", "not set up", "Could not reach")):
            break  # every other message would fail the same way; they go out on the next run
    return results


def log_for(region=None, limit=60):
    qs = ReminderLog.objects.select_related("sent_by")
    if region:
        qs = qs.filter(region=region)
    return [{"at": l.sent_at, "epid": l.epid, "stage": l.stage, "district": l.district, "to": l.phone, "name": l.contact,
             "ok": l.ok, "error": l.error, "by": l.sent_by.username if l.sent_by else "daily job"} for l in qs[:limit]]


def contacts_for(region=None):
    qs = DistrictContact.objects.all()
    if region:
        qs = qs.filter(region=region)
    return [{"id": c.id, "region": c.region, "district": c.district, "name": c.name, "phone": c.phone, "active": c.active}
            for c in qs]
