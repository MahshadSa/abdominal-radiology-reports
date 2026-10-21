"""Tests for phase2_1_patch -- synthetic data built in code, no real data."""
from ibd_reports.phase2_1_patch import FLAG_LETTER, FLAG_PHI, patch_record

# Synthetic Arabic-script placeholder (the Persian words for "sample name"), not a real name.
_ARABIC_SAMPLE = "نام نمونه"


def _record(modality: str, parse_flags: list[str] | None = None) -> dict:
    return {
        "rec_id": "REC_99999",
        "mtime_iso": "2024-01-01T00:00:00+00:00",
        "ctime_iso": "2026-01-01T00:00:00+00:00",
        "modality": modality,
        "clinical_info": "Synthetic clinical info.",
        "previous_imaging": "",
        "findings": "Synthetic findings.",
        "impression": "Synthetic impression.",
        "parse_flags": parse_flags if parse_flags is not None else [],
    }


def _assert_only_modality_and_flags_changed(before: dict, after: dict) -> None:
    assert list(after) == list(before)
    assert all(after[k] == before[k] for k in before if k not in ("modality", "parse_flags"))


def test_arabic_script_modality_blanked():
    rec = _record(_ARABIC_SAMPLE, ["non_ascii_in_modality"])
    out, flag = patch_record(rec)
    assert flag == FLAG_PHI
    assert out["modality"] == ""
    assert out["parse_flags"] == ["non_ascii_in_modality", FLAG_PHI]
    _assert_only_modality_and_flags_changed(rec, out)


def test_salutation_modality_blanked():
    rec = _record("Dear Dr. Synthetic,")
    out, flag = patch_record(rec)
    assert flag == FLAG_LETTER
    assert out["modality"] == ""
    assert out["parse_flags"] == [FLAG_LETTER]
    _assert_only_modality_and_flags_changed(rec, out)


def test_ordinary_exam_title_unchanged():
    rec = _record("MR Enterography (with & without contrast) and abdominopelvic MR angiography:")
    out, flag = patch_record(rec)
    assert flag is None
    assert out == rec


def test_plus_minus_exam_title_unchanged():
    rec = _record("Spiral CT scan of the chest (± IV contrast):", ["non_ascii_in_modality"])
    out, flag = patch_record(rec)
    assert flag is None
    assert out == rec
    assert out["parse_flags"] == ["non_ascii_in_modality"]


def test_existing_flags_kept_in_order_new_flag_last():
    rec = _record(_ARABIC_SAMPLE, ["contains_table", "no_signoff", "non_ascii_in_modality"])
    out, _ = patch_record(rec)
    assert out["parse_flags"] == ["contains_table", "no_signoff", "non_ascii_in_modality", FLAG_PHI]
    assert rec["parse_flags"] == ["contains_table", "no_signoff", "non_ascii_in_modality"]
