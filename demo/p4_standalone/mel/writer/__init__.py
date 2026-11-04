"""P4 - survey writing and safety. The five contract signatures:
  compose_survey(decision, insight, lang="both") -> Survey          (compose.py)
  render_template(key, slots, lang) -> str                           (templates.py)
  check_survey(survey) -> GuardResult(ok, failures)                  (guards.py)
  relevance(survey, insight) -> float                                (compose.py)
  write_survey_llm(decision, insight) -> Survey | None               (llm.py)
"""
from mel.writer.guards import check_survey, GuardResult
from mel.writer.templates import render_template, build_items, question_count
from mel.writer.compose import compose_survey, relevance


def write_survey_llm(decision, insight, mem=None, lang=None, client=None):
    from mel.writer import llm
    return llm.write_survey_llm(insight, mem, lang, client)
