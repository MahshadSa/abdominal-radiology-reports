# Abdominal Radiology Reports Pipeline

A reproducible pipeline for transforming a corpus of free-text abdominal radiology reports into structured, queryable records suitable for downstream clinical research in inflammatory bowel disease, primary sclerosing cholangitis, hepatobiliary disease, and oncology.

## Scope

The pipeline ingests Microsoft Word radiology reports spanning multiple modalities (MR enterography, MRCP, liver and biliary MRI, rectal cancer staging, gynaecological pelvic MRI) and produces structured outputs through a sequence of well-defined phases. Each phase is designed to be re-runnable, auditable, and additive.

## Design principles

- **Data containment.** Patient data never enters the repository. All file extensions associated with reports or derived outputs are excluded by `.gitignore`. The data tree is maintained outside the repository as a structural safeguard.
- **Provenance preservation.** Original report metadata, in particular the true report dates carried by the source files' modification timestamps, is captured before any processing, and the source files themselves are archived read-only.
- **Idempotent phases.** Each pipeline stage produces deterministic output and refuses to overwrite prior results without an explicit flag.
- **Quality through flagging.** Anomalies are recorded as flags on the affected records rather than silently corrected or excluded. A downstream audit phase reviews flagged records.
- **Synthetic-only tests.** The test suite uses hand-crafted synthetic documents; real reports never appear in tests, fixtures, or commit history.

## Pipeline phases

| Phase | Purpose |
|-------|---------|
| 0     | Extract original report metadata and create an immutable archive of source files |
| 1     | Parse documents into structured sections (modality, clinical information, comparison, findings, impression) |
| 2     | De-identify filenames and report bodies |
| 3     | Classify reports along modality and disease-category axes (multi-label, with uncertainty handling) |
| 4     | Quality audit driven by parse flags accumulated in earlier phases |
| 5     | Construct a longitudinal patient linkage table |

Phases beyond 5 belong to specific research projects (quantitative score extraction, prognostic modelling, retrieval-augmented decision support, public benchmark construction) and are tracked in separate planning documents.

## Repository layout

```
src/ibd_reports/
  phase0_metadata.py            entry point for Phase 0
  parsing/
    section_splitter.py         text to structured sections
  utils/
    paths.py                    centralised data path configuration
    logging_setup.py            timestamped per-run logging
tests/
  fixtures/                     synthetic documents only
scripts/                        ad-hoc inspection tools, outside the pipeline
notebooks/                      exploratory analysis
```

The data tree, located outside the repository, mirrors the pipeline phases with separate directories for the immutable archive, the working copy operated on by the pipeline, extracted metadata, parsed outputs, per-run logs, and a quarantine for unparseable documents.

## Setup

Requires Python 3.11 or later.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Dependencies are deliberately minimal: `python-docx` for document reading, `pandas` for tabular output, `python-dateutil` for tolerant date parsing, and `pytest` for the test suite.

## Running the pipeline

Each phase is invoked as a module. For example, Phase 0:

```powershell
python -m ibd_reports.phase0_metadata --source-doc <path> --source-docx <path>
```

All phase scripts support `--dry-run` for preview, `--force` to override safeguards against overwriting prior outputs, and write a timestamped log file for every invocation.

## Code conventions

The codebase favours plain, direct Python over abstraction. Type hints are used throughout. Logging is configured centrally; `print` is not used for diagnostics. Third-party dependencies require justification. Defensive error handling is avoided where errors are not expected; failures surface loudly rather than being swallowed.

## Status

Active development. Phase 0 is complete; Phase 1 is in progress. Subsequent phases are designed but not yet implemented.

## Authorship

Developed within an academic radiology research group. Clinical direction is provided by the principal investigator; technical implementation is led by a radiologist with computational research training.