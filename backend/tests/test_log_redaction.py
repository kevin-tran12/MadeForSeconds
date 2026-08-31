"""Unit tests for app/log_redaction.py — the backstop filter and shared
hash helper behind the P2 finding that subscriptions.py logged raw emails
and Stripe identifiers."""

import logging

from app.log_redaction import RedactionFilter, keyed_hash


def _filtered_message(raw: str, *args) -> str:
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=raw, args=args or None, exc_info=None,
    )
    RedactionFilter().filter(record)
    return record.getMessage()


class TestKeyedHash:
    def test_same_input_always_hashes_the_same(self):
        assert keyed_hash("donor@example.com") == keyed_hash("donor@example.com")

    def test_case_and_whitespace_insensitive(self):
        assert keyed_hash("Donor@Example.com") == keyed_hash("  donor@example.com  ")

    def test_different_inputs_hash_differently(self):
        assert keyed_hash("a@example.com") != keyed_hash("b@example.com")

    def test_empty_input_does_not_raise(self):
        keyed_hash("")
        keyed_hash(None)  # type: ignore[arg-type]


class TestRedactionFilter:
    def test_email_is_redacted(self):
        message = _filtered_message("Updated subscriber: donor@example.com")
        assert "donor@example.com" not in message
        assert "[redacted-email]" in message

    def test_stripe_customer_id_is_redacted(self):
        message = _filtered_message("customer cus_ABC123xyz created")
        assert "cus_ABC123xyz" not in message
        assert "cus_[redacted]" in message

    def test_stripe_subscription_id_is_redacted(self):
        message = _filtered_message("Subscription sub_QWERTY99 updated")
        assert "sub_QWERTY99" not in message
        assert "sub_[redacted]" in message

    def test_stripe_payment_intent_id_is_redacted(self):
        message = _filtered_message("intent pi_9f8e7d6c failed")
        assert "pi_9f8e7d6c" not in message

    def test_stripe_checkout_session_id_is_redacted(self):
        message = _filtered_message("session cs_test_abc123 completed")
        assert "cs_test_abc123" not in message

    def test_webhook_secret_is_redacted(self):
        """whsec_ is a credential, not just an identifier — must never
        survive in a log line under any circumstance."""
        message = _filtered_message("using whsec_supersecretvalue123")
        assert "whsec_supersecretvalue123" not in message
        assert "supersecretvalue123" not in message

    def test_event_id_is_left_alone(self):
        """Deliberate: event_id is what the fixed call sites log instead of
        an email/subscription id, specifically so it stays legible for
        correlating with Stripe's own dashboard. Redacting it here would
        defeat that fix."""
        message = _filtered_message("Payment succeeded (event=evt_1A2b3C4d)")
        assert "evt_1A2b3C4d" in message

    def test_message_with_nothing_sensitive_is_unchanged(self):
        message = _filtered_message("Skipping event evt_123 (already processed)")
        assert message == "Skipping event evt_123 (already processed)"

    def test_percent_style_args_are_redacted_after_formatting(self):
        """Filters see the record before %-args are permanently merged into
        .msg, so this must format first, redact second, not redact the raw
        %s template."""
        message = _filtered_message("donor email: %s", "person@example.com")
        assert "person@example.com" not in message
        assert "[redacted-email]" in message

    def test_multiple_identifiers_in_one_message_all_redacted(self):
        message = _filtered_message(
            "linked cus_AAA111 to donor@example.com via sub_BBB222"
        )
        assert "cus_AAA111" not in message
        assert "donor@example.com" not in message
        assert "sub_BBB222" not in message

    def test_filter_always_returns_true(self):
        """A redaction filter mutates the record; it must never suppress
        it — that's not this filter's job, and a caller checking the
        return value for "should this log?" must always see True."""
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__, lineno=1,
            msg="donor@example.com", args=None, exc_info=None,
        )
        assert RedactionFilter().filter(record) is True
