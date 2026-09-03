"""Personal details are refused at the door, before anything else happens.

The Sous Chef needs nothing about a reader except how they cook and, for a
where-to-buy question, a zip code. So any text a reader sends is checked for
personal details first: a hit ends the request with a 400 and a warning, and
the text never reaches the model, a log line, or Firestore. A zip code —
five digits, optionally ZIP+4 — is deliberately not personal information
here and passes every check.

Pure regex on purpose. This runs before the topic gate, so it must be free,
deterministic, and impossible to talk out of. It is a guard, not a
classifier: a determined reader can space out a phone number and get past
it, and that is accepted. What it must never do is refuse ordinary cooking
text, so every pattern is written to lose to quantities, temperatures,
times, and years rather than fire on them.
"""

import re

# Kinds, in the order they are checked. The first hit names the refusal.
KINDS = ("email", "id_number", "card", "phone", "birth_date", "address")

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]*[a-z]{2,}\b", re.I)

# US SSN, or an id phrased as one ("passport number AB123456").
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_ID_PHRASE_RE = re.compile(
    r"\b(?:social\s+security|ssn|passport|driver'?s?\s+licen[cs]e|licen[cs]e\s+(?:number|no)|"
    r"national\s+id|id\s+number)\b[^.\n]{0,24}?[A-Z0-9][A-Z0-9-]{4,}",
    re.I,
)

# Card numbers are 13-19 digits written in groups of four or more, so a
# numbered list ("1 2 3 4 5 …") can never look like one. Luhn decides.
_CARD_CANDIDATE_RE = re.compile(r"\b\d{4,}(?:[ -]\d{4,})*\b")

# Phones: an international +, a parenthesised area code, three separated
# groups, or a bare 10-11 digit run. A two-group 7-digit number is only a
# phone when the reader says so ("call me at 555-0100"), because 300-1000
# is a perfectly ordinary range in a recipe.
_INTL_PHONE_RE = re.compile(r"\+\d[\d\s().-]{6,18}\d")  # digits counted below
_PHONE_RES = (
    re.compile(r"\(\d{3}\)\s*\d{3}[\s.-]?\d{4}\b"),
    re.compile(r"\b\d{3}[\s.-]\d{3}[\s.-]\d{4}\b"),
    re.compile(r"\b\d{10,11}\b"),
    re.compile(r"\b(?:call|text|phone|ring|whatsapp|cell|mobile|reach)\b[^.\n]{0,20}?\b\d{3}[\s.-]?\d{4}\b", re.I),
)

_DATE_RE = r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}|\b(?:19|20)\d{2}\b)"
_BIRTH_DATE_RE = re.compile(rf"\b(?:born|birthday|birthdate|date\s+of\s+birth|dob)\b[^.\n]{{0,24}}?{_DATE_RE}", re.I)

# A street address needs a house number and a capitalised street name, so
# "2 hours drive" and "12 ct eggs" stay ordinary text; or an explicit cue
# ("I live at …") followed by a number; or an apartment/unit number.
_ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+(?:[A-Z][\w'.-]*\s+){1,3}"
    r"(?i:street|st|avenue|ave|boulevard|blvd|road|rd|drive|dr|lane|ln|way|court|ct|place|pl|highway|hwy|parkway|pkwy)\b"
)
_ADDRESS_CUE_RE = re.compile(
    r"\b(?:i\s+live\s+at|my\s+address|address\s+is|ship\s+(?:it\s+)?to|deliver\s+(?:it\s+)?to|"
    r"mail\s+(?:it\s+)?to|send\s+it\s+to)\b[^.\n]{0,40}?\d",
    re.I,
)
_UNIT_RE = re.compile(r"\b(?:apt|apartment|unit|suite|ste)\.?\s*#?\s*\d{1,5}\b", re.I)

ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")

REFUSAL_MESSAGE = (
    "Please don't share personal details like phone numbers, addresses, or emails — "
    "a zip code is all I ever need. Edit your message and ask again."
)
NOTES_REFUSAL_MESSAGE = (
    "Please keep personal details out of your cooking notes — how you cook is all I need."
)


def refusal_detail(kind: str, message: str = REFUSAL_MESSAGE) -> dict:
    """The 400 body. It names the kind spotted and never echoes the text."""
    return {"code": "personal_info", "kind": kind, "message": message}


def is_zip(text: str | None) -> bool:
    """The one piece of location a reader is ever asked for."""
    return bool(text) and bool(ZIP_RE.match(text.strip()))


def _luhn(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for index, char in enumerate(digits):
        value = int(char)
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _has_card(text: str) -> bool:
    for match in _CARD_CANDIDATE_RE.finditer(text):
        digits = re.sub(r"[ -]", "", match.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return True
    return False


def _has_phone(text: str) -> bool:
    """Country codes vary too much to spell out, so a "+" followed by eight
    or more digits counts as a phone number however it is grouped."""
    if any(pattern.search(text) for pattern in _PHONE_RES):
        return True
    return any(len(re.sub(r"\D", "", m.group())) >= 8 for m in _INTL_PHONE_RE.finditer(text))


def find_personal_info(text: str | None) -> str | None:
    """The kind of personal detail `text` carries, or None if it carries none.

    Returns one of KINDS. The caller refuses the request and tells the reader
    which kind was spotted; it never echoes the text back.
    """
    if not text:
        return None
    if _EMAIL_RE.search(text):
        return "email"
    if _SSN_RE.search(text) or _ID_PHRASE_RE.search(text):
        return "id_number"
    if _has_card(text):
        return "card"
    if _has_phone(text):
        return "phone"
    if _BIRTH_DATE_RE.search(text):
        return "birth_date"
    if _ADDRESS_RE.search(text) or _ADDRESS_CUE_RE.search(text) or _UNIT_RE.search(text):
        return "address"
    return None


def first_personal_info(texts) -> str | None:
    """The first kind found across several pieces of reader text."""
    for text in texts:
        kind = find_personal_info(text)
        if kind:
            return kind
    return None
