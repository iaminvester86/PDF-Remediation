# AI integration: access modes, terms-of-service limits, and government constraints

Research date: October 2026. Provider terms change often. Every provider adapter must link to the terms it was checked against and the date checked, and these must be re-verified before each release.

## 1. What the AI is for (and not for)

AI produces **proposals** in the internal document model. It never writes to a PDF directly. Each proposal carries the provider, model, prompt version, input hash, a confidence value, and a status (`proposed` → `accepted`/`edited`/`rejected` by a named user).

| Task | Input sent | Value | Risk |
|---|---|---|---|
| Alt text for informative images | Image crop + nearby text + caption | High: the most labour-intensive manual step | Hallucination, missing data in charts, bias. Human verification is required for public-facing documents. |
| Decorative vs informative classification | Image crop + context | High: removes noise from the review queue | A false "decorative" hides information. Default threshold is conservative. |
| Chart/diagram long descriptions | Image + extracted data/labels | Medium | Numbers can be wrong. Diff against the extracted text. |
| Heading-level and role disambiguation on hard pages | Page image + candidate tree | Medium | Low if a human confirms |
| Reading-order review on complex layouts | Page image + ordered block list | Medium | Same as above |
| Table header/scope inference for irregular tables | Table image + cell grid | Medium-high | Same as above |
| Document title suggestion | First page text | Low effort | Low |
| Link text and `Contents` suggestions | Link context | Low | Visible link text cannot be changed without editing content, so this only produces the annotation's `Contents` and a flag |
| OCR correction suggestions | Low-confidence words + image crop | Medium | Changes document text. Always human-confirmed. |
| Semantic QA "second reader" | Linearised tag tree + page image | Medium: catches what veraPDF cannot (spike 001) | Model judgement is imperfect (0.85 accuracy at best in [arXiv 2509.18965](https://arxiv.org/html/2509.18965)). Used to prioritise human review, never to certify. |

**Not used for:** declaring conformance, auto-approving anything in the "public-facing" lane, or deciding Title II exception eligibility.

## 2. The four access modes the user asked for

### 2.1 Local models (default, and the only mode allowed in the strictest profile)

- **Servers:** Ollama, llama.cpp `llama-server`, vLLM, LM Studio. All expose OpenAI-compatible HTTP, so **one adapter** covers them. The default is a localhost endpoint.
- **In-process (air-gapped, no server):** transformers or ONNX Runtime for small models.
- **Candidate models** (licence check required per model and size before shipping a default):
  - Vision-language model for alt text and page review: **Qwen3-VL 2B to 8B** (reported Apache-2.0 for released sizes; confirm on each model card), **granite-docling-258M** (Apache-2.0, document conversion only, not general alt text).
  - Avoid as defaults: Llama vision models (community licence with use restrictions), Gemma (custom terms). These can be offered as user-selected options with their licence shown.
- **Hardware reality:** a 7-8B VLM at 4-bit quantisation needs about 6-8 GB of GPU VRAM for usable speed. On CPU, expect tens of seconds per image. The product must work without AI (rules plus human review) and degrade gracefully. Throughput targets are set in Phase 3 after measurement, not assumed.

### 2.2 API keys (bring your own key)

- OpenAI, Anthropic, Google AI Studio, Mistral, OpenRouter, any OpenAI-compatible endpoint, Azure OpenAI, AWS Bedrock, Google Vertex AI.
- Keys stored in the OS keychain (`keyring`) in single-user mode, or a secrets backend (environment variables, Vault, cloud secret managers) in server mode. Never in the project database or logs.

### 2.3 Cloud identity sign-in (OAuth/SSO), where the provider supports it for third-party apps

These are the **legitimate** OAuth-style options, because the provider intends them for use by applications:

| Provider | Mechanism | Notes |
|---|---|---|
| **Azure OpenAI / Azure AI Foundry** | Microsoft Entra ID (OAuth 2.0) via `azure-identity`: device code, interactive browser, managed identity | Supports Azure Government. Common in agencies. |
| **AWS Bedrock** | IAM Identity Center (SSO) profiles via `boto3` (`aws sso login`) | Claude on Bedrock in GovCloud is FedRAMP High and DoD IL4/5 ([Anthropic](https://www.anthropic.com/news/claude-in-amazon-bedrock-fedramp-high)). AWS announced OpenAI GPT and GPT-OSS models on Bedrock GovCloud at FedRAMP High in June 2026 (reported by search results; confirm on the AWS page). |
| **Google Vertex AI** | Application Default Credentials (`gcloud auth application-default login`), workload identity | Vertex generative AI holds FedRAMP High. Claude on Vertex with Assured Workloads is listed as FedRAMP High in Anthropic's public-sector FAQ. |
| **GitHub Models** | GitHub OAuth device flow (token with models scope) | Convenient for developers. Check enterprise policy. |
| **OpenRouter** | OAuth PKCE flow that issues a user-scoped key | Third-party aggregator. Probably unsuitable for government data. |
| **OpenAI "Sign in with ChatGPT"** | OAuth/OIDC. Since DevDay (29 Sept 2026), participating apps can bill a user's ChatGPT plan, with per-app caps (reported by secondary sources) | Requires the app to be an approved participant. **Roadmap item, not v1.** Consumer plans are unsuitable for organisational data anyway. |

### 2.4 "CLI auth": using an official vendor CLI the user is already signed into

This needs care. Research found that two of the three major vendors now **prohibit third-party software from reusing the OAuth tokens of consumer subscriptions**:

- **Anthropic:** since February 2026, Free/Pro/Max OAuth tokens are for Claude Code and claude.ai only. Using them in other tools, including the Agent SDK, breaches the Consumer Terms, and server-side blocking has been reported ([The Register](https://www.theregister.com/2026/02/20/anthropic_clarifies_ban_third_party_claude_access/)). Third parties must use an API key or a cloud route (Bedrock/Vertex).
- **Google:** the Gemini CLI terms state that accessing its backend from third-party software using Gemini CLI OAuth violates the terms and can lead to suspension. Bans were enforced in 2026, and consumer "Login with Google" for the CLI was reportedly ended in June 2026 for individual tiers ([gemini-cli ToS](https://github.com/google-gemini/gemini-cli/blob/main/docs/resources/tos-privacy.md), [Discussion #20632](https://github.com/google-gemini/gemini-cli/discussions/20632)).
- **OpenAI:** offers a sanctioned route ("Sign in with ChatGPT" for participating apps, above). Community workarounds that reuse Codex tokens are unsupported.

**Design decision:**

1. The product **never reads, copies, or replays** another application's stored credentials (`~/.claude`, `~/.gemini`, `~/.codex` token files, keychain entries).
2. A **"CLI bridge" adapter** may invoke the vendor's *official* CLI binary as a subprocess in its documented non-interactive mode (for example `claude -p`, `gemini -p`, `codex exec`), with the CLI handling its own authentication. Whether this is permitted depends on the user's plan and the vendor's current terms. Enterprise, Team, or API-key-backed CLI configurations are the safe cases. Personal consumer subscriptions used for an organisation's document processing are likely outside the terms, and the UI says so.
3. The CLI bridge is **off by default**, shows the vendor's terms link and a warning on enablement, and is **disabled and locked** in the government profiles.
4. The bridge passes content on stdin, requests structured JSON output, enforces timeouts, and runs the CLI with tool use and file-system access disabled where the CLI supports such flags. (A coding-agent CLI is a powerful tool; the document content must not be able to instruct it to act.)

This satisfies the request for "AI via CLI auth" where it is legitimate, without building a feature that gets customers' accounts suspended.

## 3. Government constraints and how the design meets them

| Constraint | Source | Design response |
|---|---|---|
| Agencies must inventory AI use cases, manage "high-impact AI", and keep human oversight | OMB **M-25-21** (April 2025); procurement in **M-25-22** ([Jones Day](https://www.jonesday.com/en/insights/2025/05/omb-directs-agencies-to-accelerate-ai-adoption-and-devise-governance-strategy)) | Alt text and tagging assistance is very unlikely to be "high-impact" (it does not drive decisions about rights or safety), but agencies still need documentation. Ship an **AI use-case description template** and a model card per task. Human-in-the-loop is enforced by workflow. A per-call audit log is kept. |
| Cloud services must be FedRAMP authorised at the right impact level | FedRAMP | Provider allowlist per profile, for example "Federal Moderate/High": Bedrock GovCloud, Azure Government, Vertex Assured Workloads, local. Commercial endpoints are blocked by policy. |
| FERPA: student records may go to a vendor only under the "school official" exception with direct control and use restrictions, or with consent (34 CFR 99.31(a)(1)) | FERPA | "Education/FERPA" profile defaults to local-only. Remote providers are allowed only when an administrator records the contract basis (a DPA reference) in the profile. Optional PII redaction (Presidio) before sending text. Images cannot be redacted reliably, so image tasks stay local in this profile. |
| CUI, PII, pre-decisional documents | NIST SP 800-171, agency policy | Per-job data-classification label. Policy engine blocks remote providers for classified labels. Network egress can be disabled entirely (container with no outbound route). |
| Records retention and auditability | NARA GRS, agency policy | Immutable audit log of AI calls and human decisions, exportable. Optional cryptographic hash chain over log entries. |
| Explainability for disputes (OCR complaints, litigation) | Section 504, ADA enforcement | Per-document evidence pack: before/after validation, list of AI proposals with who accepted them, manual checklist results. |
| Model and data supply chain | EO and NIST AI RMF guidance | Model manifest with hashes and licences. No silent model downloads. Offline model bundles. |
| Prompt injection from document content | General security | Document text is wrapped and labelled as untrusted data. Outputs are schema-constrained JSON validated by Pydantic. No tool or function calling is exposed to models. Outputs over length limits, or containing URLs or instructions, are flagged. |

## 4. Policy profiles shipped by default

| Profile | Allowed providers | Auto-accept AI proposals | CLI bridge | Remote images |
|---|---|---|---|---|
| `local-only` | Local servers and in-process models | Never | Off, locked | No |
| `federal-high` | Local, Bedrock GovCloud, Azure Government, Vertex Assured Workloads (FedRAMP High) | Never | Off, locked | Yes, to listed providers only |
| `education-ferpa` | Local. Remote only with a recorded DPA. | Never for public documents | Off, locked | No (default) |
| `state-local-gov` | Local plus administrator-approved list | Never for public documents | Off (unlockable by an administrator) | Administrator decision |
| `enterprise` | Any configured | Optional thresholds for internal and archive lanes | Optional, with warning | Yes |
| `personal` | Any | Optional | Optional, with ToS warning | Yes |

Profiles are signed YAML files. An administrator can create stricter profiles. Making a shipped profile looser requires creating a new, separately named profile, so that a "federal-high" label cannot silently drift.

## 5. Adapter interface (sketch)

```python
class ModelProvider(Protocol):
    id: str                       # "ollama:qwen3-vl:8b", "bedrock-gov:anthropic.claude-...", etc.
    capabilities: set[Capability] # TEXT, VISION, JSON_SCHEMA, LONG_CONTEXT
    data_boundary: Boundary       # LOCAL, CUSTOMER_CLOUD, FEDRAMP_HIGH, COMMERCIAL
    def generate(self, req: ModelRequest) -> ModelResponse: ...  # structured output only

class AuthMethod(Enum):
    NONE_LOCAL; API_KEY; ENTRA_ID; AWS_SSO; GCP_ADC; GITHUB_DEVICE; OPENROUTER_PKCE; CLI_BRIDGE
```

The policy engine checks `data_boundary` against the job's classification and the active profile **before** any bytes leave the process. A unit test asserts that no adapter can be constructed in `local-only` with a non-local boundary.
