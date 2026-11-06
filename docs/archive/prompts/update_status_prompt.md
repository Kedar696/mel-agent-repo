# Prompt: update the project status (CLAUDE.md)

Use this after real work has landed (or stalled), so `CLAUDE.md` stays the source of truth for the next
session. `CLAUDE.md` says: update the **Status** and **Open items** sections whenever work lands, and the
date at the top. Paste everything below the line into Claude, then paste your current `CLAUDE.md` and a
short note on what changed. Fill the brackets.

---

You are updating the project-status file `CLAUDE.md` for the Digital Green "MEL Survey Agent" project. This
file is the first thing a new session reads, so it must be true, short, and current. The team is 5 people:
P1 Data & Integration, P2 Decision & Timing, P3 Scheduler/Channels/Simulator, P4 Survey Writing & Safety,
P5 Evaluation & Demo. (Old P-numbers are gone; if a change mentions an old one, map it: old P2+P3→P2,
P4+P7→P3, P5+P6→P4, P8→P5.)

## The current CLAUDE.md
[PASTE THE WHOLE CLAUDE.md HERE]

## What just changed
[1–8 bullets: what was finished, what was started, what was dropped, any new question for Digital Green.
Mark each with an owner P1–P5. Example: "P5: built the follow-up queue tab — per-reason counts, filters,
ticket detail with a suggested action."]

## Real numbers (only if the change affects Status)
Run these and paste the output. Do not invent numbers — if you can't get one, write "unknown" and say why.
- `pytest -q`  → how many tests pass
- `python -m mel.cli validate`  → invalid file count
- `python -m mel.cli eval`  (and `python scripts/readme_numbers.py`)  → golden-set metrics
- `streamlit run app/streamlit_app.py`  → read the Overview tab for survey / no-survey counts

## How to update it
1. Bump `_Last updated_` to today's date.
2. Update only the **Status (mock data)** and **Open items (owner)** sections. Leave every other section
   ("What this is", "How to run", "Decisions already made", "How the user likes to work", "Environment
   notes") alone unless something in the change list explicitly changes it.
3. Status: a few bullets of real results — tests, validate, surveys vs no-survey, golden-eval metrics,
   Streamlit tabs, and a line for anything added beyond the scaffold. No marketing words.
4. Open items: one bullet per owner (P1–P5), each listing only what is still open. Move finished work
   out; never silently drop a still-true item. Keep the "Questions owed to Digital Green" bullet at the
   end, with the same numbering (new questions appended, never reordered).
5. Do not re-open anything in the "Decisions already made" section. If a change reverses one, say so
   explicitly and show the numbers that justify it.
6. Plain English, short sentences. Keep IDs and metric names exactly as they already appear in the file.
7. Do not add tests, code, or files. This is a docs-only edit.

## Output
Give me, ready to paste back into CLAUDE.md:
1. The new `_Last updated:` line.
2. The full **Status (mock data)** section.
3. The full **Open items (owner)** section.

Then one line: what changed and why.
