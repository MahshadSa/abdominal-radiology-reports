"""Step 3 control check on PATCHED splitter. Reads source .docx, runs patched
splitter in-memory, prints requested fields. Scratch only; phase1_parsed.jsonl
is never opened for writing or touched."""
import json
import sys
from pathlib import Path
from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ibd_reports.parsing.section_splitter import split_sections

DATA = Path("../ibd-reports-data")
PARSED = DATA / "03_parsed" / "phase1_parsed.jsonl"
REPORTS = DATA / "01_working_copy" / "reports"

GLUE = [100, 137, 899, 69, 276, 289]
CONTROL = [186, 240, 844]

recs = [json.loads(l) for l in PARSED.open(encoding="utf-8")]

def f200(s):
    s = (s or "").replace("\n", " / ")
    return s if len(s) <= 200 else s[:200] + "..."

def full(s):
    return (s or "").replace("\n", " / ")

def show(i, kind):
    fn = recs[i]["filename"]
    d = split_sections(Document(str(REPORTS / (fn + ".docx"))))
    print("=" * 80)
    print(f"idx {i}  [{kind}]  file={fn!r}")
    print(f"  modality        : {full(d.get('modality'))}")
    print(f"  clinical_info   : {full(d.get('clinical_info'))}")
    print(f"  previous_imaging: {full(d.get('previous_imaging'))}")
    print(f"  findings        : {f200(d.get('findings'))}")
    print(f"  impression      : {full(d.get('impression'))}")
    print(f"  parse_flags     : {d.get('parse_flags')}")

print("########## GLUE CASES (must now populate) ##########")
for i in GLUE:
    show(i, "glue")
print()
print("########## CONTROLS (must stay absent) ##########")
for i in CONTROL:
    show(i, "control")
