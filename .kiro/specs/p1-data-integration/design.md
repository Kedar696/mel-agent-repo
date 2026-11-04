# Design: P1 Data, Contracts & Integration

## Modules
| Module | Role |
|---|---|
| `mel/config.py` | paths (`ROOT`, `DATA`, `OUT`, `PACK`, `PACK_DATA`, `FIXTURES`), languages, channels |
| `mel/data/loader.py` | JSONL / CSV readers (unchanged) |
| `mel/data/excel.py` | lazy `openpyxl` reader; `load_{insights,golden,farmers,crop_calendar}_xlsx`; `diff_records`; `check_*_parity`; `check_dir_parity`; `check_all_parity` |
| `mel/data/validate.py` | `errors`, `validate`, `why_junk`, new `failed_fields` |
| `mel/data/junk.py` | `junk_row(insight) -> (category, detail) | None` |
| `mel/pipeline.py` | `run_insight` (unchanged), `select_insights`, `PipelineResult`, `run_pipeline` |
| `mel/cli.py` | `run`, `eval`, `validate`, `junk`, `parity`; writes the files, calls `run_pipeline` |
| `scripts/compare_golden.py` | old vs new golden set |

## Data flow of `run`
```
load_insights(path) -> run_pipeline(insights, limit, farmer) -> PipelineResult(insights, outputs, rows_read)
   -> cmd_run writes surveys/ handoffs/ no_survey/ responses/   (optionally after --clean)
   -> junk_report.csv   (junk_row per processed insight)
   -> run_summary.json  (PipelineResult.counts() + input path, rows, limit, farmer)
```
`run_pipeline` is pure (writes nothing) and iterates in input order, so output is identical between runs.
No timestamps are written into `run_summary.json`.

## Decisions
- **Order of filters:** `--farmer` first, then `--limit` (first N rows of that farmer), same as the old `_select`.
- **Summary scope:** `by_rule` counts every processed row. `by_language`, `by_first_channel`, `by_priority` describe hand-offs (rows that got a
  survey), so each sums to `surveys`. Language comes from the hand-off's survey. Keys are always present, zero-filled.
- **Junk:** junk means `why_junk` is non-empty (labelled or schema failure). Schema failures win over the label. Content categories come from
  regexes on `query_summary` then `advice_summary`; first match wins. It is a report only; `mel.decision` is untouched.
- **Excel types:** golden cells arrive typed (bool, int); insights cells arrive as text. Empty cells become `None`; for `expected` an empty
  cell means the key is absent (as in the JSONL). Options are joined with ", " in the sheet and split on ", ".
- **Farmers / calendar:** all values are text, empty is `""`, exactly like `csv.DictReader`.
- **Parity:** records are flattened (`items[0].id`, `verification.needed`) and compared over the union of keys, so one-sided keys count.
  A message reads `I-000123 severity: xlsx='low' jsonl='high'`; a missing row reads `I-000123 missing in jsonl`. Folders are compared
  by relative file name (JSON files by parsed content).
- **`--clean`:** deletes the children of the four named subfolders only, then recreates them empty.
- **Exit codes:** parity differences 1; pack missing 2; argparse usage errors 2; `validate` nothing-to-check 1.

## Testing
`tests/test_data.py` (loaders, junk reasons), `tests/test_cli.py` (validate, limit, clean, run_pipeline, summary, junk report),
`tests/test_parity.py` (lazy import, Excel loaders, parity, compare_golden). Tests that need the full pack skip if it is missing.
CLI tests run `python -m mel.cli` in a subprocess with `MEL_OUT_DIR` set to a temp folder.
