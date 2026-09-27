"""
Seed data ingestion for Deployment Memory.

Reads the synthetic historical deployment dataset from
data/seed_deployments.json and stores each record into Hindsight memory
via memory.py.

Run once before demo to populate the memory bank:
    python -m src.ingestion

The seed dataset contains 8-12 records designed for discrimination value:
    - 2-3 clear failure patterns (the positive signal cases)
    - 2-3 similar-looking but safe past deployments (the decoys)
    - Variety across >= 3 different services

Ingestion is idempotent in intent — re-running adds duplicate entries,
so the bank should be cleared before re-seeding during development.
Running it a second time in the demo is safe because the bank is cleared
first via memory.py.
"""

# Seed loading and batch retain logic to be implemented in the next step.
