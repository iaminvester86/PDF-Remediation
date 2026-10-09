# PDF-Remediation

An open-source (Apache-2.0), local-first application for making PDFs accessible: PDF/UA-1 output that meets WCAG 2.x AA document requirements. It has an accessible reviewer workstation and optional, policy-controlled AI that can use local models, API keys, cloud sign-in, or official vendor CLIs.

**Status: planning.** No application code yet.

## Start here

- [`docs/PLAN.md`](docs/PLAN.md): the plan of action. Requirements, key decisions, architecture, phased work packages with gates, a step-by-step review of what could break, competitive positioning, team and effort assumptions, and the first 30 days.
- [`docs/research/`](docs/research/): supporting research.
  - [01 Review of the supplied source documents](docs/research/01-source-document-review.md)
  - [02 Competitive landscape](docs/research/02-competitive-landscape.md)
  - [03 Standards and regulations](docs/research/03-standards-and-regulations.md)
  - [04 Open-source stack and licensing](docs/research/04-open-source-stack-and-licensing.md)
  - [05 AI integration and government constraints](docs/research/05-ai-integration-and-government-constraints.md)
- [`spikes/001-tagging-feasibility/`](spikes/001-tagging-feasibility/): a reproducible experiment showing that a Python stack (pikepdf + OpenDataLoader + veraPDF) can produce PDF/UA-1 output, and that validator passes alone do not prove accessibility.
