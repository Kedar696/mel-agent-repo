# Prompts

Reusable prompts for the team.

> The team is now **5 people** (3 Nov). The team/individual contract prompts were written for the old
> 8-person split; the signed contract replaces them. Use `update_team_contracts_prompt.md` for later changes
> and tell Claude the roles are P1 Data, P2 Decision & Timing, P3 Scheduler/Channels/Simulator,
> P4 Survey Writing & Safety, P5 Evaluation & Demo.

 Copy the part below the `---` line into Claude, fill the brackets.

| File | Use it to |
|---|---|
| [team_contract_prompt.md](team_contract_prompt.md) | Generate one shared team contract (goals, roles table, timeline, sign-off) |
| [individual_contract_prompt.md](individual_contract_prompt.md) | Generate a separate one-page contract for each of P1–P8, with their baseline and open work |
| [update_team_contracts_prompt.md](update_team_contracts_prompt.md) | Update existing contracts with new work, finished items, and the optional AWS plan, in plain English |
| [v0_frontend_sketch_prompt.md](v0_frontend_sketch_prompt.md) | Get v0.dev to mock up the finished demo UI (design reference; real app stays Streamlit) |
| [update_status_prompt.md](update_status_prompt.md) | Keep CLAUDE.md's Status and Open items current after work lands (docs-only) |

| [p4_writer_safety_prompt.md](p4_writer_safety_prompt.md) | Brief Claude on the P4 writer and safety work: what exists, what changed, what is left |
| [../demo_day_plan.md](../demo_day_plan.md) | Demo-day plan (6 Nov): hackathon rules check, technical stack, order of work for the full Bedrock run, AgentCore, IaC and slides |
| [../deliverables_coverage.md](../deliverables_coverage.md) | Every requirement in Digital Green's Vision and Technical documents, checked against the repo, with the gaps in order |

Add new prompts here as `<purpose>_prompt.md` and list them in this table.
