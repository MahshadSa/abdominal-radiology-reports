"""Step 3 guarded subset test. Reads source .docx for known-affected indices,
runs the patched splitter, prints before (phase1_parsed.jsonl) vs after.
Writes nothing to corpus outputs. Scratch only."""
import json
import sys
from pathlib import Path
from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ibd_reports.parsing.section_splitter import split_sections

DATA = Path("../ibd-reports-data")
PARSED = DATA / "03_parsed" / "phase1_parsed.jsonl"
REPORTS = DATA / "01_working_copy" / "reports"

CASES = {
    "impression_glue": [100, 137, 899],
    "clinical_glue": [69, 276, 289],
    "control_absent": [186, 240, 844],
}

recs = [json.loads(l) for l in PARSED.open(encoding="utf-8")]

def trunc(s, n=140):
    s = (s or "").replace("\n", " / ")
    return s if len(s) <= n else s[:n] + "..."

def show(tag, d):
    print(f"  [{tag}] modality      : {trunc(d.get('modality'),120)}")
    print(f"  [{tag}] clinical_info : {trunc(d.get('clinical_info'))}")
    print(f"  [{tag}] prev_imaging  : {trunc(d.get('previous_imaging'),120)}")
    print(f"  [{tag}] findings      : {trunc(d.get('findings'))}")
    print(f"  [{tag}] impression    : {trunc(d.get('impression'))}")
    print(f"  [{tag}] parse_flags   : {d.get('parse_flags')}")

for group, idxs in CASES.items():
    for i in idxs:
        before = recs[i]
        fn = before["filename"]
        docx_path = REPORTS / (fn + ".docx")
        print("=" * 78)
        print(f"idx {i} | group={group} | file={fn!r} | exists={docx_path.exists()}")
        print("-- BEFORE (phase1_parsed.jsonl) --")
        show("B", before)
        after = split_sections(Document(str(docx_path)))
        print("-- AFTER (patched splitter) --")
        show("A", after)
        print()
