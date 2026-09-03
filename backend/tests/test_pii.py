"""Unit tests for the personal-information guard (app/services/pii.py).

Two duties, and the second matters as much as the first: catch what a reader
should never have to share, and stay silent on ordinary cooking text —
temperatures, quantities, ranges, times, years, and zip codes.
"""

import pytest

from app.services import pii


@pytest.mark.parametrize(
    "text,kind",
    [
        ("kevin@example.com is me", "email"),
        ("Email me at Kevin.Tran+chef@sub.example.co.uk", "email"),
        ("my ssn is 123-45-6789", "id_number"),
        ("passport number AB1234567", "id_number"),
        ("my driver's license is D1234567", "id_number"),
        ("card 4111 1111 1111 1111", "card"),
        ("4111111111111111", "card"),
        ("my number is 415-555-0100, call me about the sauce", "phone"),
        ("(415) 555-0100", "phone"),
        ("+1 415 555 0100", "phone"),
        ("+44 20 7946 0958", "phone"),
        ("4155550100", "phone"),
        ("call me at 555-0100", "phone"),
        ("I was born 04/12/1989", "birth_date"),
        ("my birthday is June 3", "birth_date"),
        ("DOB 1989", "birth_date"),
        ("I live at 12 Main St", "address"),
        ("1600 Pennsylvania Avenue", "address"),
        ("i live at 12 main street", "address"),
        ("ship it to 500 Market", "address"),
        ("Apartment 12", "address"),
        ("apt #4", "address"),
    ],
)
def test_finds_personal_information(text, kind):
    assert pii.find_personal_info(text) == kind


@pytest.mark.parametrize(
    "text",
    [
        "Is 60C safe for the chicken?",
        "Poultry 74°C / 165°F, ground meat 71°C / 160°F",
        "use 350 g flour and 1.5 kg pork belly",
        "bake at 425 F for 20-25 minutes",
        "reduce 300-1000 g of stock",
        "simmer 90-120 minutes, then rest 3 min",
        "the 2026 harvest was good",
        "12 ct eggs",
        "2 hours drive from the market",
        "1 unit of rennet",
        "do I need a passport number check for this cheese",
        "I have 2 Le Creuset Dutch ovens",
        "step 1 2 3 4 5 6 7 8 9 10 11 12 13 14",
        "cook 3 whole chickens way more often",
        "ratio 1:2:3 for the sauce",
        "call the butcher tomorrow",
        "",
        None,
    ],
)
def test_leaves_ordinary_cooking_text_alone(text):
    assert pii.find_personal_info(text) is None


@pytest.mark.parametrize("zip_code", ["94110", "94110-1234", " 10001 "])
def test_a_zip_code_is_never_personal_information(zip_code):
    """The one location detail the chef may ever ask for."""
    assert pii.find_personal_info(zip_code) is None
    assert pii.is_zip(zip_code) is True


@pytest.mark.parametrize("text", ["9411", "941101", "San Francisco", "94110 Main St", ""])
def test_is_zip_rejects_anything_but_a_zip(text):
    assert pii.is_zip(text) is False


def test_luhn_decides_what_is_a_card():
    assert pii.find_personal_info("4111 1111 1111 1112") is None  # fails Luhn
    assert pii.find_personal_info("4111 1111 1111 1111") == "card"


def test_first_personal_info_reports_the_first_hit_across_texts():
    assert pii.first_personal_info(["how long do I poach it?", "I live at 12 Main St"]) == "address"
    assert pii.first_personal_info(["kevin@example.com", "12 Main St"]) == "email"
    assert pii.first_personal_info(["how long do I poach it?", "94110"]) is None
    assert pii.first_personal_info([]) is None


def test_a_wall_of_whitespace_cannot_make_the_guard_slow():
    """Replayed history and feedback reach the guard raw, so a reader controls
    its input length. Collapsing whitespace keeps every pattern linear —
    without it "apt<n spaces>#<n spaces>x" backtracked quadratically."""
    import time

    def elapsed(n):
        probe = "apt" + " " * n + "#" + " " * n + "x"
        start = time.perf_counter()
        pii.find_personal_info(probe)
        return time.perf_counter() - start

    assert elapsed(8000) < 0.05  # was ~0.55s before the collapse
    # Quadrupling the input must not quadruple the work.
    assert elapsed(16000) < max(elapsed(4000) * 4, 0.05)


def test_collapsing_whitespace_does_not_change_what_is_found():
    assert pii.find_personal_info("apt.   4") == "address"
    assert pii.find_personal_info("I  live   at 12  Main  St") == "address"
    assert pii.find_personal_info("use   350  g   flour") is None


def test_the_refusal_body_names_the_kind_and_never_the_text():
    detail = pii.refusal_detail("phone")
    assert detail == {"code": "personal_info", "kind": "phone", "message": pii.REFUSAL_MESSAGE}
    assert "zip code" in detail["message"]
    assert all(kind in pii.KINDS for kind in ("email", "phone", "address", "card", "id_number", "birth_date"))
