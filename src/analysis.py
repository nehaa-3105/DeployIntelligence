"""
Deployment analysis orchestration for Deployment Memory.

This is the only public interface consumed by the UI. It owns the
end-to-end pipeline and coordinates memory.py, matching.py, and agent.py.

Public API:
    analyze_deployment(deployment, mode) -> AnalysisResult
        mode="baseline"  — no memory retrieval; generic LLM analysis only.
        mode="memory"    — full retrieval pipeline; memory-informed analysis.

    record_outcome(deployment_id, outcome, incident) -> None
        Called after a deployment "happens" (demo-triggered).
        Stores the new outcome as a Hindsight memory entry so the next
        analysis reflects it.

Both modes return the same AnalysisResult schema so the UI can render
them side-by-side without conditional logic.
"""

# Pipeline orchestration logic to be implemented in the next step.
