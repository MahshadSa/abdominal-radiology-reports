"""Tests for phase2_d1 name-token building and self-search."""
import pytest

from ibd_reports.phase2_d1 import (
    _build_tokens,
    _build_tokens_uncollapsed,
    _clean_filename,
    _make_token_patterns,
    _search_record,
)


# ---------------------------------------------------------------------------
# _clean_filename -- name extraction before tokenising
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        # spec examples
        ("Marzieh Jalali-1402.7.9-MRI", "Marzieh Jalali"),
        ("Ghasem Safaei_Neck&chest", "Ghasem Safaei"),
        # leading whitespace (common in corpus)
        (" Hojatollah Hodavand Khani_MRI", "Hojatollah Hodavand Khani"),
        # old-style trailing-only modality
        ("Abbas Esmaeili_MRI", "Abbas Esmaeili"),
        ("Ali Reza_MRCP", "Ali Reza"),
        ("Karimi_MRE", "Karimi"),
        ("Name_CT", "Name"),
        ("Name_CTE", "Name"),
        ("Name_PET", "Name"),
        ("Name_US", "Name"),
        # PET-CT: hyphen converted to space then matched as "PET CT"
        ("Name_PET-CT", "Name"),
        # copy-number suffixes via SEP + trail_num
        ("Abbas Esmaeili-1-2", "Abbas Esmaeili"),
        ("Mehdi Alinejad-1", "Mehdi Alinejad"),
        ("Mehdi Alinejad_2", "Mehdi Alinejad"),
        # parenthesised copy number: no SEP match, TRAIL_NUM no match,
        # but the "(1)" punctuation is stripped in _build_tokens by _PUNCT
        ("Name(1)", "Name(1)"),  # clean_filename leaves "(1)"; punct step removes it
        # bare western year
        ("Ali Karimi-2022-MRI", "Ali Karimi"),
        # bare Iranian year
        ("Sara Rezaei-1402-MRCP", "Sara Rezaei"),
        # 3-part date embedded
        ("Fateme Hosseini-12/03/2021", "Fateme Hosseini"),
        # anatomy tags in various separator forms
        ("Reza Mohammadi_liver_MRI", "Reza Mohammadi"),
        ("Nasrin Ahmadi_small_bowel", "Nasrin Ahmadi"),
        ("Ghasem Safaei_Neck&chest", "Ghasem Safaei"),
        ("Ali Karimi_abdominal_CT", "Ali Karimi"),
        ("Sara Rezaei_pelvis", "Sara Rezaei"),
        ("Maryam Jafari_brain_MRI", "Maryam Jafari"),
        # compound hyphenated first name -- hyphen becomes space, not stripped
        ("Mohammad-Ali Karimi_MRI", "Mohammad Ali Karimi"),
        # no suffix at all
        ("Karimi", "Karimi"),
        ("  Karimi  ", "Karimi"),
    ],
)
def test_clean_filename(raw: str, expected: str) -> None:
    assert _clean_filename(raw) == expected


# ---------------------------------------------------------------------------
# _build_tokens -- full pipeline including collapse-repeats
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        # spec examples (collapse-repeats active: ll->l, bb->b, ss->s)
        ("Marzieh Jalali-1402.7.9-MRI", ["marzieh", "jalali"]),
        ("Ghasem Safaei_Neck&chest", ["ghasem", "safaei"]),
        (" Hojatollah Hodavand Khani_MRI", ["hojatolah", "hodavand", "khani"]),
        # modality-only strips
        ("Ali Reza_MRCP", ["ali", "reza"]),
        ("Karimi_MRE", ["karimi"]),
        # short tokens dropped (len <= 2)
        ("Ab Cd", []),
        ("Al", []),
        # exactly 3 chars kept
        ("Ali", ["ali"]),
        ("Ali Karimi", ["ali", "karimi"]),
        # copy-number variants
        ("Mehdi Alinejad-1", ["mehdi", "alinejad"]),
        ("Mehdi Alinejad_2", ["mehdi", "alinejad"]),
        # parenthesised copy number: PUNCT step removes (), len filter removes "1"
        ("Mehdi Alinejad(1)", ["mehdi", "alinejad"]),
        # leading whitespace
        ("  Sara Rezaei", ["sara", "rezaei"]),
        # compound name: hyphen -> space -> two tokens; mm->m in Mohammad
        ("Mohammad-Ali Karimi_MRI", ["mohamad", "ali", "karimi"]),
        # accent folding
        ("Hédi Khalaf", ["hedi", "khalaf"]),
        # collapse-repeats: Abbas bb->b, Hossein ss->s
        ("Abbas Karimi", ["abas", "karimi"]),
        ("Hossein Ahmadi", ["hosein", "ahmadi"]),
        # year stripped, anatomy stripped
        ("Ali Karimi-2022-MRI", ["ali", "karimi"]),
        ("Reza Mohammadi_liver_MRI", ["reza", "mohamadi"]),
        ("Nasrin Ahmadi_small_bowel", ["nasrin", "ahmadi"]),
    ],
)
def test_build_tokens(raw: str, expected: list[str]) -> None:
    assert _build_tokens(raw) == expected


# ---------------------------------------------------------------------------
# _search_record
# ---------------------------------------------------------------------------


def _make_record(**fields: str) -> dict:
    base = {f: "" for f in ["clinical_info", "previous_imaging", "findings", "impression"]}
    base.update(fields)
    return base


def test_search_finds_token_in_findings() -> None:
    rec = _make_record(findings="Referred to Dr. Esmaeili for review.")
    patterns = _make_token_patterns(["esmaeili"])
    hits = _search_record(rec, patterns)
    assert hits == {"esmaeili": {"findings": 1}}


def test_search_case_insensitive() -> None:
    rec = _make_record(impression="Patient ESMAEILI has resolved disease.")
    patterns = _make_token_patterns(["esmaeili"])
    hits = _search_record(rec, patterns)
    assert hits == {"esmaeili": {"impression": 1}}


def test_search_whole_word_only() -> None:
    # "karimi" must NOT match inside "Karimian"
    rec = _make_record(findings="Referred by Karimian. Follow up with Karimi.")
    patterns = _make_token_patterns(["karimi"])
    hits = _search_record(rec, patterns)
    assert hits == {"karimi": {"findings": 1}}


def test_search_multiple_tokens_multiple_fields() -> None:
    rec = _make_record(
        clinical_info="Patient Karimi presents with abdominal pain.",
        previous_imaging="Prior study referenced Ali.",
        findings="No significant change.",
        impression="Stable. (Ali Karimi)",
    )
    patterns = _make_token_patterns(["ali", "karimi"])
    hits = _search_record(rec, patterns)
    assert hits["karimi"]["clinical_info"] == 1
    assert hits["karimi"]["impression"] == 1
    assert hits["ali"]["previous_imaging"] == 1
    assert hits["ali"]["impression"] == 1


def test_search_counts_multiple_occurrences() -> None:
    rec = _make_record(findings="Karimi referred. Impression noted by Karimi again.")
    patterns = _make_token_patterns(["karimi"])
    hits = _search_record(rec, patterns)
    assert hits == {"karimi": {"findings": 2}}


def test_search_no_hits() -> None:
    rec = _make_record(
        clinical_info="Normal study.",
        findings="No abnormality detected.",
        impression="Normal.",
    )
    patterns = _make_token_patterns(["alinejad", "mehdi"])
    hits = _search_record(rec, patterns)
    assert hits == {}


def test_search_empty_fields() -> None:
    rec = _make_record()
    patterns = _make_token_patterns(["karimi"])
    hits = _search_record(rec, patterns)
    assert hits == {}


def test_search_modality_field_not_searched() -> None:
    rec = {
        "modality": "Karimi MRI",
        "clinical_info": "",
        "previous_imaging": "",
        "findings": "",
        "impression": "",
    }
    patterns = _make_token_patterns(["karimi"])
    hits = _search_record(rec, patterns)
    assert hits == {}


def test_collapse_token_matches_single_letter_spelling() -> None:
    # Token is "hosein" (ss collapsed). Matches alternate romanisation in text.
    rec = _make_record(clinical_info="Patient Hosein Ahmadi referred.")
    tokens = _build_tokens("Hossein Ahmadi_MRI")
    assert "hosein" in tokens
    hits = _search_record(rec, _make_token_patterns(tokens))
    assert hits["hosein"]["clinical_info"] == 1


def test_collapse_token_misses_double_letter_spelling() -> None:
    # Demonstrates the known trade-off: collapsed "hosein" won't match "Hossein".
    rec = _make_record(clinical_info="Patient Hossein Ahmadi referred.")
    tokens = _build_tokens("Hossein Ahmadi_MRI")
    assert "hosein" in tokens
    hits = _search_record(rec, _make_token_patterns(tokens))
    # "hosein" does NOT match "Hossein" -- expected miss under collapse strategy
    assert "hosein" not in hits


def test_anatomy_and_date_stripped_before_tokenising() -> None:
    # Ensure anatomy/date junk never becomes a search token.
    tokens = _build_tokens("Reza Mohammadi_liver_MRI-2022")
    assert "liver" not in tokens
    assert "mri" not in tokens
    assert "2022" not in tokens
    assert tokens == ["reza", "mohamadi"]


def test_embedded_date_stripped() -> None:
    tokens = _build_tokens("Marzieh Jalali-1402.7.9-MRI")
    assert "1402" not in tokens
    assert tokens == ["marzieh", "jalali"]


# ---------------------------------------------------------------------------
# _build_tokens_uncollapsed -- preserves real double-letter spellings
# ---------------------------------------------------------------------------


def test_uncollapsed_keeps_double_letters() -> None:
    tokens = _build_tokens_uncollapsed("Hossein Ahmadi_MRI")
    assert "hossein" in tokens
    assert "ahmadi" in tokens


def test_uncollapsed_no_modality_junk() -> None:
    tokens = _build_tokens_uncollapsed("Abbas Esmaeili_MRI")
    assert "mri" not in tokens
    assert tokens == ["abbas", "esmaeili"]


def test_union_contains_both_forms() -> None:
    # Union of collapsed + uncollapsed should hold both "hosein" and "hossein".
    collapsed = _build_tokens("Hossein Ahmadi_MRI")
    uncollapsed = _build_tokens_uncollapsed("Hossein Ahmadi_MRI")
    union = list(dict.fromkeys(collapsed + uncollapsed))
    assert "hosein" in union
    assert "hossein" in union


def test_uncollapsed_matches_double_letter_in_text() -> None:
    # Un-collapsed form catches the double-letter spelling that collapsed misses.
    rec = _make_record(clinical_info="Patient Hossein Ahmadi referred.")
    collapsed = _build_tokens("Hossein Ahmadi_MRI")
    uncollapsed = _build_tokens_uncollapsed("Hossein Ahmadi_MRI")
    union = list(dict.fromkeys(collapsed + uncollapsed))
    hits = _search_record(rec, _make_token_patterns(union))
    assert hits["hossein"]["clinical_info"] == 1


def test_union_deduplicates_identical_tokens() -> None:
    # For names without double letters the two forms are identical; union deduplicates.
    collapsed = _build_tokens("Karimi_MRI")
    uncollapsed = _build_tokens_uncollapsed("Karimi_MRI")
    union = list(dict.fromkeys(collapsed + uncollapsed))
    assert union.count("karimi") == 1
