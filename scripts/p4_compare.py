"""Templates vs Bedrock table for P5. Writes out/p4_compare.md. Owner: P4.
    MEL_USE_LLM=1 MEL_BEDROCK_WRITE_MODEL=<large id> MEL_BEDROCK_CHECK_MODEL=<small id> MEL_BEDROCK_REGION=<region> python scripts/p4_compare.py
Without those it still runs and prints 'not run' for the model rows."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mel.config import OUT
from mel.data import load_insights
from mel.decision import decide
from mel.writer import llm
from mel.writer.compare import compare, markdown, sample_insights

models = {k: v for k, v in (("large", llm.write_model()), ("small", llm.check_model())) if v}
result = compare(sample_insights(load_insights(), decide, 50), models)
text = markdown(result)
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "p4_compare.md").write_text(text + "\n", encoding="utf-8")
print(text)
