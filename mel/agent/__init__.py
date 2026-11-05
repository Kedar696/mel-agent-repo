"""The Fasal Pulse agent (P5): Evidence Extractor -> Analyst -> Verifier -> Synthesizer, with bounded revision."""
from .orchestrator import run_agent, run_agent_to_end, verify, bedrock_guardrail, MAX_REVISIONS, MAX_PROMPT_CHARS
