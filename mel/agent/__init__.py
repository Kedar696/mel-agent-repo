"""The Fasal Pulse agent (P5): Evidence Extractor -> Analyst -> Verifier -> Synthesizer, with bounded revision."""

from .orchestrator import (
    run_agent,
    run_agent_to_end,
    verify,
    bedrock_guardrail,
    guardrail_from_env,
    judge_from_env,
    payload_options,
    MAX_REVISIONS,
    MAX_PROMPT_CHARS,
)
