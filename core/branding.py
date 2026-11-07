"""Letterheads and support contacts shared by every page: the GHS logos, the organisation line and how a region is
named, and the support team's WhatsApp number and email."""
import base64
from pathlib import Path

from . import orgunits

IMG = Path(__file__).resolve().parent / "static" / "core" / "img"
LOGO = IMG / "logo-web.png"     # GHS emblem with the Upper East RHD mark
EMBLEM = IMG / "ghs-emblem.png"
RHD = IMG / "rhd-mark.png"
IMAGE_TYPES = {b"\x89PNG\r\n\x1a\n": (".png", "image/png"), b"\xff\xd8\xff": (".jpg", "image/jpeg")}

SUPPORT_WHATSAPP = "0246828504"
SUPPORT_EMAIL = "babayahaya.mohammed@ghs.gov.gh"


def support():
    return {"wa_number": SUPPORT_WHATSAPP, "wa_link": "https://wa.me/233" + SUPPORT_WHATSAPP.lstrip("0"),
            "email": SUPPORT_EMAIL}


def data_uri(path):
    """An image as a data: URI. The pages draw their logos into exported PNGs, which only works with inline images."""
    if not path or not path.exists():
        return ""
    body = path.read_bytes()
    mime = next((m for magic, (_, m) in IMAGE_TYPES.items() if body.startswith(magic)), "image/png")
    return f"data:{mime};base64," + base64.b64encode(body).decode()


def org_for(unit):
    if orgunits.is_national(unit):
        return "Ghana Health Service · Disease Surveillance (National)"
    return f"Ghana Health Service · Regional Health Directorate, {unit['name']} (Surveillance)"


def unit_label(unit):
    """How a unit is named on the pages: "Upper East Region", or "Ghana (all regions)" for the national view."""
    return unit["name"] + (" (all regions)" if orgunits.is_national(unit) else " Region")


def logo_for(unit):
    """The letterhead logo: the RHD mark belongs to Upper East, so other regions get the GHS emblem."""
    return LOGO if unit["name"] == orgunits.DEFAULT_REGION else EMBLEM


def letterhead(unit):
    """Template context for a page's header and footer."""
    return {"logo": data_uri(logo_for(unit)), "logo_alt": "Ghana Health Service · " + unit["name"],
            "region_up": unit_label(unit).upper(), "org": org_for(unit)}
