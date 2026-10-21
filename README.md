# Abdominal Radiology Reports Pipeline

A reproducible pipeline for transforming a large corpus of free-text abdominal radiology reports into structured, de-identified, queryable records suitable for downstream clinical research in inflammatory bowel disease, primary sclerosing cholangitis, hepatobiliary disease, and oncology.

The pipeline is the enabling infrastructure. It is designed so that the structured corpus can support longitudinal, patient-level analysis rather than one-off cross-sectional extraction, and so that any extraction built on top of it is traceable to source text and trusted by radiologists.

## Research context

The corpus is being developed to support patient-level and longitudinal research that single-report extraction does not address: reconstructing structural damage trajectories over time, relating disease activity to cumulative damage across a patient's imaging history, and systematically recovering the range of measurements relevant to both ulcerative colitis and Crohn's disease from free text. A shared design commitment runs through this work: every extracted claim is traceable to a source sentence, uncertainty is represented explicitly rather than collapsed into a binary, and uncertain cases are escalated for human review rather than silently resolved.

Specific studies built on the structured corpus, including quantitative score extraction and prognostic modelling, are tracked in separate planning documents.

## Corpus

Approximately 9,800 Microsoft Word radiology reports spanning multiple modalities: MR enterography (IBD and Crohn's disease), MRCP (primary sclerosing cholangitis), liver and biliary MRI, rectal cancer staging, and gynaecological pelvic MRI. One file per report. Reports follow a consistent free-text structure of modality, clinical information, optional prior-imaging reference, findings, and impression.

## Design principles

- **Data containment.** Patient data never enters the repository. All file extensions associated with reports or derived outputs are excluded by `.gitignore`, and the data tree is maintained outside the repository as a structural safeguard. The metadata table that maps source files to patients is itself treated as protected health information and is never committed or copied into de-identified outputs.
- **Provenance preservation.** Original report metadata, in particular the true report dates carried by the source files' modification timestamps, is captured before any processing, and the source files themselves are archived read-only.
- **Idempotent phases.** Each stage produces deterministic output and refuses to overwrite prior results without an explicit flag. Expected output counts are stated before each run so results can be verified rather than trusted.
- **Validation before production.** Extraction and de-identification logic is designed and validated on held-out subsets, with expected numbers stated in advance, before any full-corpus run.
- **Quality through flagging.** Anomalies are recorded as flags on the affected records rather than silently corrected or excluded. A downstream audit phase reviews flagged records.
- **Synthetic-only tests.** The test suite uses hand-crafted synthetic documents; real reports never appear in tests, fixtures, or commit history.

## Pipeline phases

The pipeline produces the structured, de-identified corpus that the research programme runs on. Each phase is re-runnable, auditable, and additive.

| Phase | Purpose | Status |
|-------|---------|--------|
| 0 | Capture original report metadata and create an immutable, read-only archive of source files | Complete |
| 1 | Parse documents into structured sections (modality, clinical information, comparison, findings, impression) | Complete |
| 1b | Cluster filenames to identify repeat-patient reports ahead of longitudinal linkage | Complete |
| 2 | De-identify filenames and report bodies to HIPAA Safe Harbor | Complete |
| 3 | Classify reports along modality and disease-category axes (multi-label, with explicit uncertainty handling) | Designed |
| 4 | Quality audit driven by parse flags accumulated in earlier phases | Designed |
| 5 | Construct a longitudinal patient linkage table | Designed |

### De-identification (Phase 2)

De-identification targets the HIPAA Safe Harbor standard. Names are removed by matching each report only against the patient tokens derived from its own filename, after a normalisation step that strips modality, anatomy, and date fragments. In-text dates are reduced through an ordered set of passes that deliberately leaves numeric clinical measurements untouched. Email and telephone patterns are caught by validated backstop patterns. Every run emits a non-identifying audit trail keyed by row index, recording per-category removal counts and flags for anomalous records, so the scrub can be reviewed without exposing patient data. Filenames are then replaced by per-report identifiers, assigned by a seeded shuffle so that identifier order carries no alphabetical signal; the mapping table is minted once, never regenerated, and held outside the repository. Per-patient identifiers are deferred until repeat-patient identity is confirmed, so that a single patient is never split across two identifiers.

### Classification (Phase 3)

Classification operates on two independent axes, modality and disease category, and is multi-label. Findings expressed with affirmative language ("consistent with", "in keeping with", "appearances are those of") are treated as positive; hedged language ("cannot exclude", "possible", "differential includes") is recorded as an uncertainty flag rather than a positive label. This distinction is carried through to all downstream extraction.

Research phases beyond the structured corpus belong to specific research projects and are tracked in separate planning documents.

## Repository layout

```
src/ibd_reports/
  phase0_metadata.py            metadata capture and read-only archiving
  phase1_parse.py               full-corpus parsing into structured records
  phase1b_name_clustering.py    repeat-patient filename clustering
  phase2_scrub.py               de-identification scrubber
  phase2_d1.py                  name self-search token derivation
  phase2_recon*.py              de-identification reconnaissance passes
  phase2_recall_check.py        post-scrub recall verification
  phase2_rekey.py               per-report identifier assignment
  stoplist.txt                  common-word exclusions for name matching
  parsing/
    section_splitter.py         text to structured sections
  utils/
    paths.py                    centralised data path configuration
    logging_setup.py            timestamped per-run logging
tests/                          synthetic-only test suite
  fixtures/                     hand-crafted synthetic documents
scripts/                        ad-hoc inspection tools, outside the pipeline
notebooks/                      exploratory analysis
```

The data tree is maintained entirely outside the repository and mirrors the pipeline phases: an immutable read-only archive of source files, the working copy operated on by the pipeline, extracted metadata, parsed outputs, per-run logs, the de-identified corpus with its audit trail, and a quarantine for unparseable documents. Held-out subsets used for validating de-identification logic are kept separate from the full corpus.

## Setup

Requires Python 3.11 or later. The pipeline is packaged as an installable module.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

Dependencies are deliberately minimal: `python-docx` for document reading, `pandas` for tabular output, `python-dateutil` for tolerant date parsing, and `pytest` for the test suite.

## Running the pipeline

Each phase is invoked as a module. For example, Phase 0:

```powershell
python -m ibd_reports.phase0_metadata --source-doc <path> --source-docx <path>
```

Later phases follow the same pattern. All phase scripts support `--dry-run` for preview, `--force` to override safeguards against overwriting prior outputs, and write a timestamped log file for every invocation.

## Code conventions

The codebase favours plain, direct Python over abstraction. Type hints are used throughout. Logging is configured centrally; `print` is not used for diagnostics. Third-party dependencies require justification. Defensive error handling is avoided where errors are not expected; failures surface loudly rather than being swallowed.

## Status

Active development. Phases 0, 1, 1b, and 2 are complete on the full corpus. De-identification and its validation now cover every parsed field, including the modality header. Phase 3 classification is next; Phases 4 and 5 are designed and pending implementation. The research programme begins once the de-identified, structured corpus is locked.