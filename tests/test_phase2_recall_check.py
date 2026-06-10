"""Tests for phase2_recall_check -- synthetic fixtures only, no real data."""
from ibd_reports.phase2_d1 import _make_token_patterns
from ibd_reports.phase2_recall_check import (
    build_roster,
    regex_sweep_counts,
    search_record,
)


# ---------------------------------------------------------------------------
# build_roster
# ---------------------------------------------------------------------------


def test_build_roster_unions_and_dedupes() -> None:
    roster = build_roster(["Ali Karimi_MRI", "Karimi Reza_MRCP"])
    assert "ali" in roster
    assert "karimi" in roster
    assert "reza" in roster
    # "karimi" appears in both filenames but only once in the set
    assert sum(1 for t in roster if t == "karimi") == 1


def test_build_roster_no_stoplist_applied() -> None:
    # "Poor" would normally be filtered by the scrubber's stoplist, but the
    # recall-check roster is the independent net and must not apply it.
    roster = build_roster(["Abbas Sabzi Poor"])
    assert "poor" in roster


# ---------------------------------------------------------------------------
# regex_sweep_counts
# ---------------------------------------------------------------------------


def test_sweep_date4_year_first_fires() -> None:
    counts = regex_sweep_counts("Previous imaging dated 1402.7.9 shows no change.")
    assert counts["date_4digit"] == 1


def test_sweep_date4_year_last_fires() -> None:
    counts = regex_sweep_counts("Follow-up scan on 03.01.2021.")
    assert counts["date_4digit"] == 1


def test_sweep_date2_fires() -> None:
    counts = regex_sweep_counts("Previous MRE (03.01.21).")
    assert counts["date_2digit"] == 1


def test_sweep_year_only_fires_on_residual_year() -> None:
    counts = regex_sweep_counts("Scan dated 1402 reviewed.")
    assert counts["year_only"] == 1
    assert counts["date_4digit"] == 0
    assert counts["date_2digit"] == 0


def test_sweep_two_group_measurement_untouched() -> None:
    counts = regex_sweep_counts("CHD measured at 8.5 mm.")
    assert counts["date_4digit"] == 0
    assert counts["date_2digit"] == 0


def test_sweep_email_fires() -> None:
    counts = regex_sweep_counts("Contact via user@hospital.ir for results.")
    assert counts["email"] == 1


def test_sweep_phone_fires() -> None:
    counts = regex_sweep_counts("Call 09123456789 for appointment.")
    assert counts["phone"] == 1


def test_sweep_clean_text_all_zero() -> None:
    counts = regex_sweep_counts("Normal study, no abnormality. [NAME] [DATE]")
    assert all(v == 0 for v in counts.values())


# ---------------------------------------------------------------------------
# search_record
# ---------------------------------------------------------------------------


def _make_record(**fields: str) -> dict:
    base = {f: "" for f in ["clinical_info", "previous_imaging", "findings", "impression"]}
    base.update(fields)
    return base


def _patterns(tokens: set[str]) -> dict:
    return dict(_make_token_patterns(list(tokens)))


def test_search_finds_cross_report_token() -> None:
    roster = {"karimi", "ali"}
    rec = _make_record(clinical_info="Patient Karimi referred. Ali also seen.")
    rows = search_record(rec, roster, _patterns(roster))
    assert ("karimi", "clinical_info", 1) in rows
    assert ("ali", "clinical_info", 1) in rows


def test_search_whole_word_boundary() -> None:
    # "karimi" must NOT fire inside "Karimian"
    roster = {"karimi"}
    rec = _make_record(findings="Referred by Karimian today.")
    rows = search_record(rec, roster, _patterns(roster))
    assert rows == []


def test_search_case_insensitive() -> None:
    roster = {"karimi"}
    rec = _make_record(impression="KARIMI noted.")
    rows = search_record(rec, roster, _patterns(roster))
    assert rows == [("karimi", "impression", 1)]


def test_search_hyphen_separated_name_matches() -> None:
    roster = {"ali"}
    rec = _make_record(findings="Seen by Dr. Ali-Reza for review.")
    rows = search_record(rec, roster, _patterns(roster))
    assert rows == [("ali", "findings", 1)]


def test_search_no_hits_on_clean_text() -> None:
    roster = {"karimi", "ali"}
    rec = _make_record(
        clinical_info="Normal study.",
        findings="No abnormality detected.",
        impression="Stable. [NAME] [DATE]",
    )
    rows = search_record(rec, roster, _patterns(roster))
    assert rows == []


def test_search_empty_fields() -> None:
    roster = {"karimi"}
    rec = _make_record()
    rows = search_record(rec, roster, _patterns(roster))
    assert rows == []


def test_search_multiple_occurrences_counted() -> None:
    roster = {"karimi"}
    rec = _make_record(findings="Karimi referred. Follow up with Karimi.")
    rows = search_record(rec, roster, _patterns(roster))
    assert rows == [("karimi", "findings", 2)]


def test_search_stoplisted_word_still_fires() -> None:
    # "poor" is in the scrubber's stoplist, but the recall check applies no
    # stoplist, so a roster containing "poor" must still flag it.
    roster = {"poor"}
    rec = _make_record(findings="Colon prep was poor.")
    rows = search_record(rec, roster, _patterns(roster))
    assert rows == [("poor", "findings", 1)]


def test_search_multiple_fields() -> None:
    roster = {"ali", "karimi"}
    rec = _make_record(
        clinical_info="Ali Karimi referred.",
        previous_imaging="Ali noted.",
        findings="Stable.",
        impression="No change. Karimi.",
    )
    rows = search_record(rec, roster, _patterns(roster))
    assert ("ali", "clinical_info", 1) in rows
    assert ("karimi", "clinical_info", 1) in rows
    assert ("ali", "previous_imaging", 1) in rows
    assert ("karimi", "impression", 1) in rows
    assert len(rows) == 4
