"""The line list's code lists, as in the regional meningitis workbook ("1-Yes", "03-NmW", ...).

Each list is (code, label). The database stores the code; pages and downloads show "code-label", as the workbook
did. `normalise` reads the many spellings found in old workbooks ("9 unknown", "Missing", "2 GND", "Yes") back to
a code, so imports and reports never see two versions of the same answer.
"""
import re

YES_NO = [("1", "Yes"), ("2", "No"), ("9", "Unknown")]
SEX = [("M", "Male"), ("F", "Female"), ("U", "Unknown")]
OUTCOME = [("1", "Alive"), ("2", "Dead"), ("3", "On treatment"), ("4", "Referred"), ("9", "Unknown")]
VACCINE = [("1", "MenA conjugate (MenAfriVac)"), ("2", "MenAC"), ("3", "MenACW"), ("4", "MenACWY"), ("5", "MenFive (NmCV-5)"),
           ("9", "Unknown")]
PCV = [("1", "Yes, 1 dose"), ("2", "Yes, 2 doses"), ("3", "Yes, 3 doses"), ("4", "No"), ("9", "Unknown")]
GRAM = [("1", "GPD"), ("2", "GND"), ("3", "GPR"), ("4", "GNR"), ("5", "Other"), ("6", "No organism seen"), ("7", "Not done")]
RAPID = [("1", "NmA"), ("2", "NmC"), ("3", "NmW"), ("4", "NmY"), ("5", "Negative"), ("6", "Not done")]
LATEX = [("1", "NmA"), ("2", "NmC"), ("3", "NmW/Y"), ("4", "NmB/E. coli K1"), ("5", "NmX"), ("6", "S. pneumoniae"),
         ("7", "Hib"), ("8", "Strep B"), ("9", "Negative"), ("10", "Not done")]
# Culture, PCR and the final lab result share one list; 03-NmW, 08-S. pneumoniae and 14-Negative are the
# workbook's own codes.
PATHOGEN = [("01", "NmA"), ("02", "NmC"), ("03", "NmW"), ("04", "NmY"), ("05", "NmB"), ("06", "NmX"),
            ("07", "Nm indeterminate"), ("08", "S. pneumoniae"), ("09", "Hib"), ("10", "H. influenzae non-b"),
            ("11", "Strep B"), ("12", "Other bacteria"), ("13", "Contaminated"), ("14", "Negative"), ("15", "Not done")]
CLASSIFICATION = [("1", "Confirmed"), ("2", "Probable"), ("3", "Suspect")]

YES, NO, UNKNOWN = "1", "2", "9"
DEAD = "2"
CONFIRMED, PROBABLE, SUSPECT = "1", "2", "3"
NOT_A_RESULT = {"13", "14", "15"}  # contaminated, negative, not done: no pathogen found
BACTERIA = [c for c, _ in PATHOGEN if c not in NOT_A_RESULT]

LISTS = {
    "yesno": YES_NO, "sex": SEX, "outcome": OUTCOME, "vaccine": VACCINE, "pcv": PCV, "gram": GRAM, "rapid": RAPID,
    "latex": LATEX, "pathogen": PATHOGEN, "classification": CLASSIFICATION,
}

# Spellings seen in old workbooks, by list, after `key()`: what they mean.
ALIASES = {
    "yesno": {"y": "1", "yes": "1", "n": "2", "no": "2", "unk": "9", "unknown": "9", "dontknow": "9", "missing": "9",
              "nk": "9"},
    "sex": {"m": "M", "male": "M", "f": "F", "female": "F", "u": "U", "unknown": "U"},
    "outcome": {"alive": "1", "recovered": "1", "discharged": "1", "dead": "2", "died": "2", "death": "2",
                "ontreatment": "3", "admitted": "3", "referred": "4", "unknown": "9", "missing": "9"},
    "vaccine": {"menaconjugate": "1", "menafrivac": "1", "mena": "1", "menac": "2", "menacw": "3", "menacwy": "4",
                "menfive": "5", "nmcv5": "5", "unknown": "9", "missing": "9"},
    "pcv": {"yes1dose": "1", "1dose": "1", "yes2doses": "2", "2doses": "2", "pcv132": "2", "yes3doses": "3",
            "3doses": "3", "no": "4", "unknown": "9", "missing": "9"},
}


def key(text):
    """Lower-case letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def label(name, code):
    """'1-Yes' for a code, '' for none."""
    if code in (None, ""):
        return ""
    return next((f"{c}-{t}" for c, t in LISTS[name] if c == code), str(code))


def normalise(name, value):
    """(code, problem): the code a workbook cell means, or (None, None) for a blank cell, or (None, why) when it
    can't be read. Accepts '1-Yes', '1', 'Yes', '9 unknown', 'Missing', '03-NmW', 'NmW', 'S. pneumoniae'."""
    if value is None or str(value).strip() == "":
        return None, None
    choices, text = LISTS[name], str(value).strip()
    if isinstance(value, float) and value.is_integer():
        text = str(int(value))
    for c, t in choices:  # this module's own downloads: "M-Male", "03-NmW"
        if text.lower() == f"{c}-{t}".lower():
            return c, None
    m = re.match(r"^\s*(\d+)\s*[-–.:)]?\s*(.*)$", text)
    number, rest = (m.group(1), m.group(2)) if m else (None, text)
    by_label = {key(t): c for c, t in choices} | ALIASES.get(name, {})
    if rest and key(rest) in by_label:  # the words decide: "1-MenAfriVac" and "2-No" (PCV) mean what they say
        return by_label[key(rest)], None
    if number is not None:
        for c, _ in choices:
            if c.lstrip("0") == number.lstrip("0") or c == number:
                return c, None
    if key(text) in by_label:
        return by_label[key(text)], None
    return None, f"“{text}” is not on the list"


def as_options(name):
    return [[c, f"{c}-{t}"] for c, t in LISTS[name]]
