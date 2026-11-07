"""The Weekly IDSR page's data: a region's store, its AFP cases for the bulletin, and the map and SORMAS pictures
on page 2 of the bulletin (kept per region in IDSR_IMAGES)."""
from datetime import datetime

from django.conf import settings

from afp import cases
from core import orgunits
from core.branding import IMAGE_TYPES, data_uri

from . import store as idsr

IMAGE_SLOTS = ("map", "sormas")


def image_file(slot, region):
    return next((p for ext, _ in IMAGE_TYPES.values() if (p := settings.IDSR_IMAGES / f"idsr-{slot}-{region}{ext}").exists()), None)


def set_image(slot, body, region):
    """Store (or with an empty body, remove) a region's map or SORMAS picture shown on page 2 of the bulletin."""
    if slot not in IMAGE_SLOTS:
        raise ValueError("Unknown picture.")
    ext = next((e for magic, (e, _) in IMAGE_TYPES.items() if body.startswith(magic)), None)
    if body and not ext:
        raise ValueError("Choose a PNG or JPEG picture.")
    if not region or not region.isalnum():
        raise ValueError("Set the region code first.")
    if (old := image_file(slot, region)) is not None:
        old.unlink()
    if body:
        settings.IDSR_IMAGES.mkdir(parents=True, exist_ok=True)
        (settings.IDSR_IMAGES / f"idsr-{slot}-{region}{ext}").write_bytes(body)


def bulletin_code(case, districts):
    """The bulletin district code of an AFP case: its register code, else its district name matched loosely."""
    code = str(case.get("code") or "").strip().upper()
    if any(code == c for c, _ in districts):
        return code
    b = orgunits.bare(case.get("district"))
    hit = next((c for c, n in districts if orgunits.bare(n) == b), None)
    if hit is None:
        _, d = orgunits.district_region(case.get("district") or "")
        hit = d[0] if d and any(d[0] == c for c, _ in districts) else None
    return hit or code


def snapshot(store=None, live=True):
    """The page data for `store`: a Store (one region), a store file, or by default the main store."""
    store = store if isinstance(store, idsr.Store) else idsr.Store(store)
    snap = store.snapshot()
    national = getattr(store, "national", False)
    unit = orgunits.national_unit() if national else orgunits.region_of(store.region)
    try:  # this region's AFP cases for the bulletin's AFP counts and 60-day tracker; no names leave the register
        # (nationally every case, counted under its region's code)
        afp = [{k: c.get(k) for k in ("epid", "district", "code", "onset", "outcome", "report", "week")}
               | {"dcode": c["code"] if national else bulletin_code(c, store.districts)}
               for c in (cases.region_cases(settings.AFP_REGISTER, unit) if unit else [])]
    except Exception:
        afp = []
    return snap | {"generated": datetime.now().isoformat(timespec="seconds"), "source": store.path.name, "live": live,
                   "national": national,
                   "saved": store.path.exists(), "regionsOnFile": idsr.regions_on_file(),
                   "appUrl": "/", "afp": afp, "images": {s: data_uri(image_file(s, store.code)) for s in IMAGE_SLOTS}}
