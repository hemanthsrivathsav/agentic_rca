"""Supersede: decision provenance for AI agents.

The package is organised in layers:

- ``store``       storage interface and the SQLite implementation
- ``knowledge``   versioned documents, SUPERSEDES edges and retrieval
- ``llm``         swappable model clients (offline mock, Azure OpenAI)
- ``tracing``     span recorder that wraps every model and tool call
- ``runtime``     step loop with checkpoints, breakpoints, resume and fork
- ``rules``       breakpoint rules checked between steps
- ``provenance``  claim attribution, version checks, lineage, replay, stability
- ``demo``        synthetic KYC onboarding workflow used in the demo

Only the Python standard library is used here. FastAPI lives in ``api/``.
"""

__version__ = "0.1.0"
