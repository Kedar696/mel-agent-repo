# Requirements: P1 Data, Contracts & Integration

## Introduction
P1 owns loading the pack data, validating every artifact against its JSON Schema, the batch pipeline glue, the
command line, CI and the integration guarantees between the Excel workbooks and the JSON/CSV files.

## Requirements

### R-1 Validate must not pass on nothing
**User story:** As a maintainer, I want `validate` to fail when there is nothing to check, so CI cannot go green on an empty folder.
1. WHEN the output folder is missing or holds no JSON files THEN `validate` SHALL exit non-zero, unless `--allow-empty` is given.
2. `validate` SHALL print how many files it checked.
3. WHEN a file is not valid JSON THEN `validate` SHALL report it by file name, count it as invalid, and keep going.

### R-2 Safe `--limit`
1. WHEN `--limit` is negative THEN `run` and `junk` SHALL stop with a usage error and no traceback.
2. WHEN `--limit 0` THEN nothing SHALL be processed.

### R-3 Lazy Excel dependency
`import mel.cli, mel.pipeline, mel.data` SHALL NOT load `openpyxl`; it is imported only inside functions that read a workbook.

### R-4 CI
CI SHALL use Python 3.12 only and run, in order: `pip install -e ".[dev]"`, `pytest -q`, `python -m mel.cli run --simulate`,
`validate`, `eval`, `parity`, with no `continue-on-error` and no `|| true`.

### R-5 `run --clean`
`run --clean` SHALL empty only `surveys/`, `handoffs/`, `no_survey/` and `responses/` in the output folder. Other files stay.

### R-6 `run_pipeline`
`mel.pipeline.run_pipeline(insights, limit=None, farmer=None)` SHALL filter and loop over the insights and return a non-None result;
`cmd_run` SHALL call it; `run_insight` SHALL be unchanged; the same input SHALL give identical output.

### R-7 Run summary
`run` SHALL write `run_summary.json` with counts by rule (R1 to R8), language, first channel and priority, the input path and the rows
processed. Counts SHALL respect `--limit` and `--farmer`. `run` SHALL print a summary naming the rule ids. The file SHALL be described in `docs/TEAM.md`.

### R-8 Junk report
`run` SHALL write `junk_report.csv` (`insight_id`, `category`, `detail`), one row per junk insight processed. Schema failures use
`schema_failure` and name every failed field. Schema-valid junk uses a content category (`greeting`, `thanks`, `about_the_app`,
`unclear_voice`, `acknowledgement`, plus a fallback) and SHALL NOT mention "schema". No survey decision SHALL change.

### R-9 Excel loaders
`load_golden_xlsx`, `load_farmers_xlsx` and `load_crop_calendar_xlsx` SHALL return exactly what `load_golden`, `load_farmers` and
`load_crop_calendar` return for the same data, including nested `insight` / `expected` objects and `items`.

### R-10 Parity
`python -m mel.cli parity` SHALL work with no arguments against the committed pack, compare the four workbooks and the `config/rules`,
`config/schemas`, `data/mock/scenarios`, `data/mock/outcomes` folders, name each difference by row id and field or by file name, catch
missing rows and one-sided keys, and exit non-zero on any difference.

### R-11 Golden comparison
`scripts/compare_golden.py OLD NEW` SHALL print golden ids added, removed and changed and counts by rule R1 to R8; identical files print
no golden ids. The README SHALL document the steps for a new golden set.

### R-12 Documentation and config
README quick start for both OSes with `MEL_DATA_DIR`, `MEL_OUT_DIR`, an OneDrive warning and `parity`; `CLAUDE.md` and
`scripts/make_mock_data.py` use the committed pack location; `.env.example` has `MEL_TIMING_BASIS=brief` and a blank `ANTHROPIC_API_KEY`;
`docs/questions_for_digital_green.md` holds the three questions; `docs/TEAM.md` has "Merge order", "Interfaces" and "Where each person starts".

### R-13 No behaviour change
Full-pack counts (R1 723, R2 25, R3 1287, R4 875, R5 1312, R6 111, R7 115, R8 2551; surveys 5102, handoffs 2551, no_survey 4448,
responses 2551; 0 invalid) and scores (decision 96.0%, rule 96.0%, channel 100%, window 0%) SHALL NOT change.
