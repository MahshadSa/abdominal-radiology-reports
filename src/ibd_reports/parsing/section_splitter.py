import logging
import re
from docx import Document

logger = logging.getLogger(__name__)

_HEADERS: dict[str, re.Pattern[str]] = {
    "clinical_info": re.compile(r"^\s*clinical\s+information\s*:\s*(.*)$", re.IGNORECASE),
    "previous_imaging": re.compile(r"^\s*comparison\s*:\s*(.*)$", re.IGNORECASE),
    "impression": re.compile(r"^\s*impression\s*:\s*(.*)$", re.IGNORECASE),
}


def split_sections(doc: Document) -> dict:
    """Split a radiology report Document into named sections."""
    accum: dict[str, list[str]] = {
        "clinical_info": [], "previous_imaging": [], "findings": [], "impression": [],
    }
    flags: list[str] = []
    paragraphs = doc.paragraphs

    if not paragraphs:
        flags.append("empty_document")
        return {
            "modality": "", "clinical_info": "", "previous_imaging": "",
            "findings": "", "impression": "", "parse_flags": flags,
        }

    modality = paragraphs[0].text.strip()

    header_positions: dict[str, int] = {}
    current_section: str | None = None
    awaiting_content_for: str | None = None
    past_first_header = False
    found_signoff = False

    for i, para in enumerate(paragraphs):
        if i == 0:
            continue

        text = para.text.strip()

        if text.lower().startswith("sincerely"):
            found_signoff = True
            break

        matched = False
        for section_key, pattern in _HEADERS.items():
            m = pattern.match(text)
            if m:
                header_positions[section_key] = i
                past_first_header = True
                awaiting_content_for = None
                inline = m.group(1).strip()
                if inline:
                    accum[section_key].append(inline)
                    current_section = section_key if section_key == "impression" else None
                else:
                    awaiting_content_for = section_key
                    current_section = section_key
                matched = True
                break

        if matched or not text or not past_first_header:
            continue

        if awaiting_content_for is not None:
            accum[awaiting_content_for].append(text)
            if awaiting_content_for != "impression":
                current_section = None
            awaiting_content_for = None
        elif current_section == "impression":
            accum["impression"].append(text)
        else:
            accum["findings"].append(text)

    if not modality:
        flags.append("no_modality")
    if "clinical_info" not in header_positions:
        flags.append("no_clinical_information")
    if "impression" not in header_positions:
        flags.append("no_impression")
    if not found_signoff:
        flags.append("no_signoff")
    if doc.tables:
        flags.append("contains_table")
    if len(modality) > 150:
        flags.append("modality_long")
    if (
        "clinical_info" in header_positions
        and "impression" in header_positions
        and header_positions["impression"] < header_positions["clinical_info"]
    ):
        flags.append("section_out_of_order")
    if any(ord(c) > 127 for c in modality):
        flags.append("non_ascii_in_modality")

    return {
        "modality": modality,
        "clinical_info": "\n".join(accum["clinical_info"]),
        "previous_imaging": "\n".join(accum["previous_imaging"]),
        "findings": "\n".join(accum["findings"]),
        "impression": "\n".join(accum["impression"]),
        "parse_flags": flags,
    }
