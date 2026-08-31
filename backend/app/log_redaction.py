"""Structured redaction of emails and Stripe identifiers from application logs.

Cloud Logging is this project's production log sink, and log *access* is a
broader surface than "who can query Firestore directly" — anyone with read
access to logs could otherwise reconstruct the supporter list or correlate
payment identifiers just by reading them. `subscriptions.py` logged raw
emails and Stripe customer/subscription/session identifiers at its handful
of webhook and cancellation call sites; this module is both the fix (a
shared hash helper those call sites now use instead of the raw value where
no better identifier is available) and a backstop (a `logging.Filter`
installed on the root logger's handlers that scrubs anything else that
slips through — including code this pass didn't specifically audit).

Deliberately NOT redacted: Stripe *event* ids (`evt_...`). `event_id` is
this project's own webhook idempotency key (`processed_events`, doc id =
event_id) and the identifier Stripe's own dashboard/API use to look up a
specific delivery — it is exactly what an operator needs in hand when
debugging a failed webhook from its log line. Redacting it here would
defeat the entire point of switching the webhook call sites over to
logging it instead of a raw email or subscription id.
"""

import hashlib
import logging
import re

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# [A-Za-z0-9_]+, not just alnum: cs_ checkout session ids commonly carry an
# extra segment (cs_test_..., cs_live_...), and \b never matches between two
# underscores or between a letter and an underscore, so excluding "_" from
# the class would silently stop the match partway through and leave the
# remainder of the id in the log line. Deliberately excludes evt_ — see the
# module docstring.
_STRIPE_ID_RE = re.compile(r"\b(cus|sub|pi|cs|whsec)_[A-Za-z0-9_]+\b")


def keyed_hash(value: str) -> str:
    """One-way, unsalted hash of a lowercased/stripped identifier — an
    email, typically — for correlating log lines or records about the same
    person without storing or logging the original value a second time.

    Unsalted is deliberate: the same input must always hash to the same
    output in every context that calls this, or two log lines (or a log
    line and a stored record) about the same person stop correlating.
    """
    return hashlib.sha256((value or "").strip().lower().encode()).hexdigest()


class RedactionFilter(logging.Filter):
    """Attach to root-logger handlers (see main.py) — NOT to a named
    logger. Records from child loggers propagate straight to the root
    logger's handlers without passing through the root Logger object's own
    filters, so a filter added to that Logger would silently never run for
    them; a filter added to its handlers runs for every record regardless
    of which module logged it.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = _EMAIL_RE.sub("[redacted-email]", message)
        redacted = _STRIPE_ID_RE.sub(lambda m: f"{m.group(1)}_[redacted]", redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True
