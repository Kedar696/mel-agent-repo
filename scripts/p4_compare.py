"""Templates vs Bedrock table for P5. Writes out/p4_compare.md. Owner: P4.
    MEL_USE_LLM=1 MEL_BEDROCK_WRITE_MODEL=<large id> MEL_BEDROCK_CHECK_MODEL=<small id> MEL_BEDROCK_REGION=<region> python scripts/p4_compare.py
Without those it still runs and prints 'not run' for the model rows.
Add MEL_JUDGE=1 MEL_JUDGE_MODEL=<judge id> for an AI-judge relevance column (1-5, P5's judge, checked against people).
Samples 50 surveys from the full participant pack when it is in the repo (MEL_DATA_DIR still wins)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mel.config import OUT, PACK_DATA, flag, full_pack
from mel.data import load_insights
from mel.decision import decide
from mel.writer import llm
from mel.writer.compare import compare, markdown, sample_insights

models = {k: v for k, v in (("large", llm.write_model()), ("small", llm.check_model())) if v}
insights = load_insights(PACK_DATA / "insights.jsonl" if full_pack() else None)
judge = None
if flag("MEL_JUDGE"):
    from mel.evaluation.judge import BedrockClient

    judge = BedrockClient()  # MEL_JUDGE_MODEL
result = compare(sample_insights(insights, decide, 50), models, judge=judge)
text = markdown(result)
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "p4_compare.md").write_text(text + "\n", encoding="utf-8")
print(text)
