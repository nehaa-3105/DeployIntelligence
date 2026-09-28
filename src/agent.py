"""
LLM agent for Deployment Memory.

Wraps Gemini to produce structured risk assessments.
The agent never discovers matches — it only explains pre-matched evidence.

Two tools exposed to the LLM:
    get_deployment_memory(service, signals)
        Called in memory mode only.
        Invokes matching.py + memory.py and returns matched past incidents.

    assess_risk(deployment, past_incidents)
        Called in both modes (past_incidents is [] in baseline mode).
        Produces: risk_level, reasoning, cited_incidents, recommendation.

The agent receives a strictly bounded context:
    - In baseline mode: only the proposed deployment fields.
    - In memory mode: proposed deployment + MatchSummary (candidates,
      counts, confidence label). The LLM is instructed to cite only
      incidents present in the provided context.

Output is always a structured AnalysisResult — never free-form text.
"""

# Gemini client initialisation and tool/function-calling logic
# to be implemented in the next step.
