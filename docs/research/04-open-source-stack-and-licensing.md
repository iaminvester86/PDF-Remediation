# Open-source stack and licence analysis

Versions and licences below were pulled from PyPI metadata and project READMEs on 2026-10-09. The repository is licensed **Apache-2.0**. This document is engineering analysis, not legal advice. Legal review of the licence policy is a Phase 0 exit criterion.

## 1. Licence policy (proposed)

| Class | Licences | Rule |
|---|---|---|
| **Core-allowed** | MIT, BSD, Apache-2.0, ISC, PSF, MPL-2.0 (file-level copyleft), LGPL (dynamic linking or unmodified use) | May be a required dependency |
| **Optional plugin only** | GPL-2/3, AGPL-3, model weights with use restrictions (OpenRAIL-M variants, Llama community licence, Gemma terms, custom "open source" licences with extra conditions) | Never imported by core. Installed only by explicit `pip install pdf-remediation[plugin-x]` or a separate package. Licence notice shown at install and in the UI. Disabled in the "government" profile unless an administrator enables it. |
| **External program (subprocess)** | e.g. Ghostscript (AGPL), Tesseract (Apache), veraPDF (GPL/MPL), Java runtime | Invoked as a separate process. Container images that bundle them must ship their licence texts and source offers. |
| **Proprietary adapters** | Adobe PDF Services API, PDFix SDK, cloud LLM APIs | Optional adapters behind interfaces. The core must work fully without them. |

Why it matters: companies and governments adopting an Apache-2.0 tool expect to be able to embed and redistribute it. An accidental AGPL import (PyMuPDF is the usual culprit) would impose AGPL obligations on anyone distributing the combined work, and many legal departments block AGPL outright. A CI licence gate (section 5) enforces the policy.

## 2. Component selection

### 2.1 PDF read/write (the critical path)

| Library | Version | Licence | Role | Decision |
|---|---|---|---|---|
| **pikepdf** (qpdf) | 10.16.0 | MPL-2.0 | Low-level object and content-stream editing, struct-tree writing, XMP, linearised save | **Core writer.** Proven in spike 001 to produce PDF/UA-1-passing output. Requires Python ≥3.11. |
| **pypdfium2** | 5.14.0 | BSD-3 / Apache-2.0 | Rendering (pixel diff, thumbnails, contrast sampling), text with positions | **Core renderer.** Chromium's PDF engine, permissive licence. |
| **pdfminer.six** / **pdfplumber** | 20260107 / 0.11.10 | MIT | Character-level text, fonts, positions for heuristics | **Core** analysis helpers |
| **pypdf** | 6.20.0 | BSD-3 | Pure-Python fallback, forms | Optional/helper |
| **fontTools** | 4.66.1 | MIT | Font inspection, ToUnicode repair, subsetting checks | **Core**, for the font workstream |
| **PyMuPDF** | 1.28.2 | **AGPL-3.0** or commercial | Fast rendering and text extraction | **Excluded from core.** pypdfium2 + pdfminer cover the same needs. |
| **borb** | 3.0.9 | AGPL-3.0 | PDF creation | Excluded |
| **pdfix-sdk** | 9.3.0 | Proprietary | Commercial auto-tag/remediation | Optional adapter only |

### 2.2 Structure detection (layout, reading order, tables)

| Library | Version | Licence | Notes | Decision |
|---|---|---|---|---|
| **opendataloader-pdf** | 2.5.12 | Apache-2.0 (Java 11+ runtime) | Deterministic local layout, XY-Cut++ reading order, tables, auto-tag to Tagged PDF. Benchmarks are self-published. | **Default structure engine** (spike 001: good on a clean two-column document). Its PDF/UA export is a paid add-on, which we replace with our own finisher. |
| **docling** + **docling-ibm-models** | 2.137.0 / 4.0.3 | MIT (code). Model licences per model. | Layout model, TableFormer, reading order, OCR integration | **Second engine** for complex tables and scans (also the backend of ODL's hybrid mode). Model licences must be checked one by one. |
| **granite-docling-258M** | n/a | Apache-2.0 | Small VLM for page-to-DocTags | Optional local VLM path for hard pages |
| **marker-pdf** / **surya-ocr** | 2.0.0 / 0.22.1 | Code Apache-2.0. **Weights: modified OpenRAIL-M**, free only for research, personal use, and organisations under $5M funding/revenue. | High quality | **Optional plugin only.** Most government agencies and large companies exceed the threshold. |
| **MinerU** | 4.0.11 | "MinerU Open Source License" (Apache-2.0 + extra conditions) | Strong extraction | Optional plugin, after legal review |
| **doclayout-yolo**, **ultralytics** | 0.0.4 / 8.4.175 | AGPL-3.0 | Layout detection | Excluded from core |
| **camelot-py**, **img2table** | 2.0.0 / 2.0.0 | MIT | Ruled-table extraction | Helpers for table cross-checks |
| **layoutparser** | 0.3.4 | Apache-2.0 | Older and little maintained | Not selected |

### 2.3 OCR

| Library | Version | Licence | Decision |
|---|---|---|---|
| **OCRmyPDF** + **Tesseract** | 17.13.0 | MPL-2.0 / Apache-2.0 | **Default OCR.** Produces the text layer, which we then tag. Needs Ghostscript (AGPL, external program). Document how to install it, and ship it only in container images with licence text. |
| **RapidOCR** (ONNX) | 3.10.0 | Apache-2.0 | Lightweight alternative engine, CPU-friendly |
| **PaddleOCR** | 3.7.0 | Apache-2.0 | Higher accuracy option, heavier |
| **EasyOCR** | 1.7.2 | Apache-2.0 | ODL hybrid default |
| **python-doctr** | 1.1.0 | Apache-2.0 | Alternative |

OCR output must carry per-word confidence. Low-confidence pages go to the human lane and are never auto-published.

### 2.4 Validation

| Tool | Version | Licence | Decision |
|---|---|---|---|
| **veraPDF** CLI/REST | 1.28.2 (supports ua1, ua2, wt1a, wt1r, PDF/A) | GPLv3+ **or** MPLv2+ | **Core validator, run as a sidecar process** (choose the MPL option). Requires a Java runtime. There is no Python validator of comparable coverage, so the Java dependency is accepted deliberately. |
| PAC 2024/2026 | n/a | Freeware, Windows GUI | Optional manual cross-check. Not scriptable, so not in CI. |

### 2.5 Language, text quality, PII

| Library | Licence | Use |
|---|---|---|
| **lingua-language-detector** 2.2.0 | Apache-2.0 | Per-span language (`Lang`). Needs Python ≥3.12; fall back to **fasttext** lid model (MIT code; check model licence) on 3.11. |
| **textstat** | MIT | Readability metrics (informational only) |
| **presidio-analyzer** + **spaCy** | MIT | Optional PII detection and redaction before any text is sent to a remote AI provider |
| **rapidfuzz** | MIT | Fuzzy matching (alt text vs nearby caption, duplicate detection) |

### 2.6 AI access

| Library | Version | Licence | Decision |
|---|---|---|---|
| **httpx** + our own adapters | n/a | BSD | **Default.** One OpenAI-compatible HTTP adapter covers Ollama, llama.cpp server, vLLM, LM Studio, OpenRouter, Azure OpenAI, and many others. Native adapters for Anthropic, Google, and Bedrock follow. |
| **openai** / **anthropic** / **google-genai** SDKs | 3.28.0 / 1.13.0 / 2.29.0 | Apache-2.0 / MIT / Apache-2.0 | Optional extras per provider |
| **boto3**, **azure-identity**, **google-auth** | Apache-2.0 / MIT / Apache-2.0 | Cloud SSO and OAuth credential flows (Bedrock, Azure OpenAI with Entra ID, Vertex with ADC) |
| **litellm** | 1.104.2 | MIT | **Optional only, hash-pinned.** It was the subject of a PyPI supply-chain compromise on 24 March 2026 (versions 1.82.7 and 1.82.8 carried a credential stealer; [NetSPI](https://www.netspi.com/blog/executive-blog/ai-ml-pentesting/litellm-supply-chain-compromise/), [Comet](https://www.comet.com/site/blog/litellm-supply-chain-attack/)). Its very large dependency surface is a poor fit for government deployments. |
| **ollama** client | 0.6.3 | MIT | Not needed; Ollama exposes an OpenAI-compatible endpoint |
| **llama-cpp-python**, **vllm**, **transformers**, **onnxruntime** | MIT / Apache-2.0 | Optional in-process inference for air-gapped installs without a model server |

### 2.7 Application

| Layer | Choice | Licence | Rationale |
|---|---|---|---|
| API | **FastAPI** 0.143 + Pydantic | MIT | Typed schemas shared with the CLI and the report JSON |
| Jobs | **RQ** 2.12 (Redis) for server mode; in-process executor for single-user mode | BSD-2 | Simpler than Celery. Dramatiq is LGPL (acceptable but unnecessary). |
| Storage | SQLite (single user), PostgreSQL (server); filesystem or S3-compatible object store | n/a | Air-gap friendly |
| Auth (users) | OIDC/SAML through **Authlib** / python3-saml | BSD / MIT | Login.gov, Entra ID, Okta, Google Workspace |
| Front end | **pdf.js** (Apache-2.0) viewer plus **USWDS** components (public domain/CC0) | n/a | USWDS is the U.S. federal design system with accessible components. A plain web UI works in any browser and can be served from localhost for single-user use. |
| CLI | Typer or argparse | MIT / PSF | |
| Desktop shell (later) | pywebview (BSD) around the same local web UI | BSD | Avoids maintaining a second UI. PySide6 (LGPL) would mean a second, separately accessible UI to build and audit. |
| Signing (optional) | **pyHanko** 0.37 | MIT | Re-sign documents after remediation, where the customer holds keys |

## 3. Things that cannot be done in Python alone

1. **Validation:** veraPDF (Java). Accept a Java runtime.
2. **Default structure engine:** OpenDataLoader (Java core with Python wrapper). The same Java runtime covers both.
3. **OCR binaries:** Tesseract (C++), Ghostscript (C). These are system packages.

So the stack is "Python application, Java and C sidecars". Distribution must therefore be a container image or an installer that bundles a JRE. The plan provides both, plus a pip install for developers.

## 4. Supply-chain controls (required for government buyers)

- Hash-pinned lock files (`uv lock` or pip-tools with `--generate-hashes`). Install with `--require-hashes`.
- Wheelhouse plus model bundle for air-gapped installs, with checksums and signatures.
- SBOM (CycloneDX) generated in CI for both Python and Java dependencies. Container images scanned.
- Releases signed with Sigstore/cosign. PyPI Trusted Publishing (OIDC); no long-lived tokens.
- Audit for `.pth` files and post-install hooks in dependencies (the LiteLLM attack vector).
- Model files: record source URL, licence, SHA-256, and date fetched in a model manifest. Refuse to load unknown hashes in the government profile.
- Dependabot or Renovate with a review gate. No auto-merge for runtime dependencies.

## 5. CI licence gate

`pip-licenses` (or `reuse` plus a custom script) runs on every pull request against the core dependency closure. The build fails if any package resolves to GPL, AGPL, SSPL, or an unknown licence outside the plugin extras. A test asserts that `import pdf_remediation` does not transitively import `fitz`/`pymupdf`, `ultralytics`, or `marker`.
