"""Compare the simulator's output with the pack's 183 reference answer records, field by field.
Owner: P1 (thin wrapper; the check itself is P3's `mel.simulator.reference_check`).

Run:  python scripts/compare_outcomes.py        prints the report; exit 1 on any mismatch
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mel.simulator.reference_check import main

if __name__ == "__main__":
    raise SystemExit(main())
