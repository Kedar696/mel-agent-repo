# Release checklist (freeze)

P1 runs this at the freeze, after `lucas-p1` (and the other branches) are merged to `main`. It is
the exact sequence a new user follows from the README, then the tag commands. **Do not create the
tag until the freeze is called.** Commands are shown without trailing `# comments` (a zsh shell
treats `#` as an argument).

## 0. Before you start
- You are on `main`, fully merged, working tree clean: `git switch main && git pull && git status`.
- Python 3.12 is available (`python3.12 --version`).

## 1. Clean-checkout rehearsal (prove the README works for a new user)
Do this in a throwaway folder, not your working copy, so it matches a first-time clone.
```
git clone --branch main --single-branch https://github.com/michvinh-7/mel-agent-repo.git /tmp/mel_release
cd /tmp/mel_release
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
python -m mel.cli run --simulate --clean
python -m mel.cli validate
python -m mel.cli eval
python -m mel.cli parity
```
Expected (mock data): all tests pass; `run` prints a `schedule:` line with `cap_violations=0`;
`validate` 0 invalid; `eval` decision/rule 100% (mock); `parity` differences 0.

Full pack:
```
export MEL_DATA_DIR=mel-survey-agent-participant-pack/participant-pack/data
export MEL_OUT_DIR=/tmp/mel_release_out
python -m mel.cli run --simulate --clean
python -m mel.cli validate
python -m mel.cli eval
```
Expected (full pack): `run` → sent+moved = 2,038 out (1,613 sent, 425 moved, 480 merged, 98 skipped,
0 cap_violations); `validate` 0 invalid; `eval` decision/rule 99.3% (one miss, G-0145).

REST API:
```
pip install -r requirements-api.txt
uvicorn mel.api.app:app
```
In another terminal (Windows: use `curl.exe`):
```
curl http://127.0.0.1:8000/healthz
curl -X POST http://127.0.0.1:8000/surveys -H 'content-type: application/json' -d "$(head -n 1 data/mock/insights.jsonl)"
curl "http://127.0.0.1:8000/surveys/due?at=2027-01-22T09:00:00+05:30"
```
Expected: `{"status":"ok"}`; a `201` survey response; a `200` due list. Stop the server (Ctrl-C).

Docker:
```
docker build -t mel-survey-agent-api .
docker run --rm -p 8000:8000 mel-survey-agent-api
curl http://127.0.0.1:8000/healthz
```
Expected: build succeeds; `/healthz` returns ok; the container's HEALTHCHECK reports `healthy`
(`docker inspect --format '{{.State.Health.Status}}' <container>`). Stop and remove the container.

Streamlit (just confirm it loads, then stop):
```
streamlit run app/streamlit_app.py
```
Expected: it serves on http://localhost:8501 with no error in the console. Ctrl-C to stop.

When the rehearsal is clean, delete the throwaway folder: `rm -rf /tmp/mel_release /tmp/mel_release_out`.

## 2. Final checks on `main` itself
Back in your real working copy on `main`:
```
pytest -q
python -m mel.cli run --simulate --clean
python -m mel.cli validate
python -m mel.cli eval
python -m mel.cli parity
```
All green. CI on `main` is also green (it builds the API image and smoke-tests `/healthz`).

## 3. Tag the release (only when the freeze is called)
Suggested version: **v1.0.0** (first public release). Tag the exact `main` commit and push the tag.
```
git switch main
git pull
git tag -a v1.0.0 -m "Fasal Pulse - MEL Survey Agent v1.0.0 (freeze)"
git push origin v1.0.0
```
To check it afterwards: `git show v1.0.0 --stat | head` and confirm it appears under Tags on GitHub.

If you tag the wrong commit, delete and redo before anyone builds from it:
```
git tag -d v1.0.0
git push origin :refs/tags/v1.0.0
```

## 4. After tagging
- Confirm the tag is on GitHub and points at the merged `main`.
- Note the freeze commit hash and the `v1.0.0` tag in `CLAUDE.md` Status.
