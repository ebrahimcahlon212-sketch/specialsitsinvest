# Spec amendments, version 1, 4 October 2026

These override docs/system-spec.md where they differ.

1. Quality gates are strict only for refclass outputs and new commands. Existing commands run the gates in warn-only mode, printing any failure without stopping, until phase 3 adds the steps that produce evidence.
2. Research steps, including drafts, reviews, checks, ask and explain, never receive the evidence instructions and are never stopped by a gate.
3. A gate may only re-read sources inside the deal's filings or work folders, never model output.
4. Collectors for the FDA sources and for EDGAR are built and tested against small saved samples of real responses, stored under tests/fixtures with their download dates. Ebrahim runs the live build himself.
5. The IBKR collector reuses the kit's existing price code and is verified during that live build.
6. Every existing command must behave exactly as it did before phase 1, with tests that show it.
