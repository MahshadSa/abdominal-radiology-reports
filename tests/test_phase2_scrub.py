"""Tests for phase2_scrub -- synthetic fixtures only, no real data."""
import re

import pytest

from ibd_reports.phase2_d1 import _make_token_patterns
from ibd_reports.phase2_scrub import _get_filename, _scrub_record, _scrub_text


def _pats(tokens: list[str]) -> list[tuple[str, re.Pattern]]:
    return _make_token_patterns(tokens)


# ---------------------------------------------------------------------------
# _scrub_text: name replacement
# ---------------------------------------------------------------------------


def test_name_replaced_in_text():
    text = "Referred by Karimi for follow-up."
    out, names, d4, d2, em, ph = _scrub_text(text, _pats(["karimi"]))
    assert "[NAME]" in out
    assert "Karimi" not in out
    assert names == 1


def test_name_whole_word_boundary():
    # "karimi" must NOT fire inside "Karimian"
    text = "Patient seen by Karimian today."
    out, names, d4, d2, em, ph = _scrub_text(text, _pats(["karimi"]))
    assert names == 0
    assert "Karimian" in out


def test_name_case_insensitive():
    text = "KARIMI referred."
    out, names, d4, d2, em, ph = _scrub_text(text, _pats(["karimi"]))
    assert names == 1
    assert "KARIMI" not in out


def test_name_multiple_occurrences_counted():
    text = "Karimi referred. Follow up with Karimi."
    out, names, d4, d2, em, ph = _scrub_text(text, _pats(["karimi"]))
    assert names == 2


def test_name_no_tokens_leaves_text_unchanged():
    text = "Normal study, no abnormality."
    out, names, d4, d2, em, ph = _scrub_text(text, [])
    assert out == text
    assert names == 0


# ---------------------------------------------------------------------------
# _scrub_text: date pass 1 (4-digit-year 3-group -> year only)
# ---------------------------------------------------------------------------


def test_date4_year_first_reduced_to_year():
    # Iranian year-first format
    text = "Previous imaging dated 1402.7.9 shows no change."
    out, names, d4, d2, em, ph = _scrub_text(text, [])
    assert "1402" in out
    assert "7.9" not in out
    assert d4 == 1


def test_date4_year_last_reduced_to_year():
    # Western year-last format
    text = "Follow-up scan on 03.01.2021."
    out, names, d4, d2, em, ph = _scrub_text(text, [])
    assert "2021" in out
    assert "03.01" not in out
    assert d4 == 1


def test_date4_slash_separator():
    text = "Scan 1401/05/12 reviewed."
    out, names, d4, d2, em, ph = _scrub_text(text, [])
    assert "1401" in out
    assert "05/12" not in out
    assert d4 == 1


def test_date4_does_not_fire_on_two_group_shape():
    # 8.5 is a 2-group measurement, must be untouched
    text = "CHD measured at 8.5 mm."
    out, names, d4, d2, em, ph = _scrub_text(text, [])
    assert "8.5" in out
    assert d4 == 0


# ---------------------------------------------------------------------------
# _scrub_text: date pass 2 (2-digit-year -> [DATE])
# ---------------------------------------------------------------------------


def test_date2_replaced():
    # Truncated Iranian date with 2-digit year
    text = "Previous MRE (03.01.21)."
    out, names, d4, d2, em, ph = _scrub_text(text, [])
    assert "[DATE]" in out
    assert "03.01.21" not in out
    assert d2 == 1


def test_date2_not_triggered_after_pass1_residual():
    # After pass 1 replaces "1402.7.9" -> "1402", the bare year "1402"
    # must NOT be matched by the 3-group pass-2 pattern.
    text = "Scan 1402.7.9 reviewed."
    out, names, d4, d2, em, ph = _scrub_text(text, [])
    assert d4 == 1
    assert d2 == 0
    assert "[DATE]" not in out


# ---------------------------------------------------------------------------
# _scrub_text: 2-group shapes left UNTOUCHED
# ---------------------------------------------------------------------------


def test_two_group_duct_diameter_untouched():
    text = "CHD measured at 8.5 mm."
    out, names, d4, d2, em, ph = _scrub_text(text, [])
    assert "8.5" in out
    assert d4 == 0
    assert d2 == 0


def test_ca_19_9_untouched():
    # CA 19-9 uses a hyphen separator; date patterns only match [/.]
    text = "Tumour marker CA 19-9 is elevated."
    out, names, d4, d2, em, ph = _scrub_text(text, [])
    assert "19-9" in out
    assert d4 == 0
    assert d2 == 0


# ---------------------------------------------------------------------------
# _scrub_text: email backstop
# ---------------------------------------------------------------------------


def test_email_replaced():
    text = "Contact via user@hospital.ir for results."
    out, names, d4, d2, em, ph = _scrub_text(text, [])
    assert "[EMAIL]" in out
    assert "user@hospital.ir" not in out
    assert em == 1


def test_no_email_no_substitution():
    text = "No contact info provided."
    out, names, d4, d2, em, ph = _scrub_text(text, [])
    assert em == 0


# ---------------------------------------------------------------------------
# _scrub_text: phone backstop
# ---------------------------------------------------------------------------


def test_phone_mobile_replaced():
    text = "Call 09123456789 for appointment."
    out, names, d4, d2, em, ph = _scrub_text(text, [])
    assert "[PHONE]" in out
    assert "09123456789" not in out
    assert ph == 1


def test_phone_landline_replaced():
    text = "Office: 02112345678."
    out, names, d4, d2, em, ph = _scrub_text(text, [])
    assert "[PHONE]" in out
    assert ph == 1


def test_phone_with_plus98_replaced():
    text = "International: +989123456789."
    out, names, d4, d2, em, ph = _scrub_text(text, [])
    assert "[PHONE]" in out
    assert ph == 1


# ---------------------------------------------------------------------------
# _scrub_record integration
# ---------------------------------------------------------------------------


def _make_record(**kwargs) -> dict:
    base = {
        "filename": "Test Person",
        "modality": "MRI small bowel",
        "clinical_info": "",
        "previous_imaging": "",
        "findings": "",
        "impression": "",
        "parse_flags": "",
    }
    base.update(kwargs)
    return base


def test_modality_never_scrubbed():
    rec = _make_record(
        filename="Ali Karimi",
        modality="MRI Karimi protocol",
        clinical_info="Patient Karimi referred.",
    )
    scrubbed, counts = _scrub_record(rec)
    # modality untouched
    assert scrubbed["modality"] == "MRI Karimi protocol"
    # clinical_info scrubbed
    assert counts["names"] == 1


def test_source_filename_normalised_to_filename():
    rec = {
        "source_filename": "Hossein Ahmadi.docx",
        "modality": "MRI",
        "clinical_info": "Patient Hossein referred.",
        "previous_imaging": "",
        "findings": "",
        "impression": "",
        "parse_flags": "",
    }
    scrubbed, counts = _scrub_record(rec)
    assert "filename" in scrubbed
    assert "source_filename" not in scrubbed
    assert scrubbed["filename"] == "Hossein Ahmadi"
    # "hossein" token (uncollapsed) matches "Hossein" in clinical_info
    assert counts["names"] == 1


def test_scrub_record_date_in_previous_imaging():
    rec = _make_record(previous_imaging="Previous MRE (03.01.21).")
    scrubbed, counts = _scrub_record(rec)
    assert "[DATE]" in scrubbed["previous_imaging"]
    assert counts["dates_2digit"] == 1


def test_scrub_record_counts_across_all_four_fields():
    rec = _make_record(
        filename="Ali Karimi",
        clinical_info="Ali Karimi referred.",
        previous_imaging="Ali noted.",
        findings="Stable. (Karimi)",
        impression="No change. Ali.",
    )
    scrubbed, counts = _scrub_record(rec)
    # "ali" hits: clinical_info(1), previous_imaging(1), impression(1) = 3
    # "karimi" hits: clinical_info(1), findings(1) = 2
    # collapsed "ali" is 3 chars, kept; "karimi" is 6 chars, kept
    assert counts["names"] >= 4


def test_get_filename_from_filename_field():
    assert _get_filename({"filename": "Ali Karimi"}) == "Ali Karimi"


def test_get_filename_from_source_filename():
    assert _get_filename({"source_filename": "Ali Karimi.docx"}) == "Ali Karimi"


def test_get_filename_source_without_docx():
    assert _get_filename({"source_filename": "Ali Karimi"}) == "Ali Karimi"


# ---------------------------------------------------------------------------
# Stoplist
# ---------------------------------------------------------------------------


def test_stoplist_prevents_poor_false_positive():
    # "poor" is in the stoplist; it must not replace the English adjective in body text
    rec = _make_record(
        filename="Abbas Sabzi Poor",
        findings="Colon totally underdistended in entire length with poor preparation.",
    )
    scrubbed, counts = _scrub_record(rec)
    assert counts["names"] == 0
    assert "poor" in scrubbed["findings"]
    assert "[NAME]" not in scrubbed["findings"]
