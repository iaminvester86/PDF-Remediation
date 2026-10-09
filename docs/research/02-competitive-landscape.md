# Competitive landscape: PDF remediation and checking tools

Research date: October 2026. Most of the information below comes from vendor websites and vendor-authored comparison articles (for example, Continual Engine's "10 Best PDF Remediation Tools of 2026" ranks its own PREP product first). Independent, peer-reviewed comparisons of remediation *accuracy* are scarce. Claims are labelled **[vendor]** where the only source is the vendor, and **[unverified]** where I could not confirm them. Pricing is quote-only for most products, and the figures here should be treated as indicative.

Two pages could not be fetched directly from this research environment because of its network policy (iaccessible.com and continualengine.com). Their content was gathered through search-engine extracts, and should be spot-checked in a browser before external use.

## 1. Market segments

| Segment | What it does | Examples |
|---|---|---|
| Desktop remediation editors | Tag-tree, reading-order, and table editing on one PDF at a time | Adobe Acrobat Pro, CommonLook PDF (desktop plugin), axesPDF, PDFix Desktop, Foxit, ABBYY FineReader |
| Web/cloud remediation platforms | Auto-tag, then guided human correction in a browser, often with batch features | PREP (Continual Engine), Equidox, CommonLook web (Allyant, 2025), EqualWeb PDF, 247 Portal |
| Scanning, assessment, and monitoring | Crawl sites, find PDFs, score them, track over time, report | **iAccessible (Revelo Software)**, Siteimprove, Level Access, Pope Tech, Silktide |
| APIs and SDKs | Programmatic auto-tagging and remediation | Adobe PDF Services Accessibility Auto-Tag API, PDFix SDK, OpenDataLoader PDF (open core) |
| Validators/checkers | Pass/fail against PDF/UA and WCAG | veraPDF (open source), PAC 2024/2026 (free, Windows), axesCheck (web), Acrobat checker |
| Alternative-format generators | Serve an accessible HTML version instead of fixing the PDF | DocAccess, ASU/AWS PDF-to-HTML path |
| Services | Human remediation by the page | Many vendors; iAccessible Level 3, Accessibility on Demand, Microassist, and others |

## 2. Product notes

### 2.1 iAccessible (Revelo Software): the benchmark the user named

Sources: iaccessible.com pages *Solutions*, *AI Remediation Options*, *Accessibility Assistant*; revelosoftware.com. All **[vendor]**.

- **What it is:** a web accessibility and PDF testing platform for WCAG and Section 508. It offers a Section 508 Assessment that scans a website, and a PDF Assessment that locates all PDFs on a site and counts the barriers by type. It includes remediation tracking, reporting, and monitoring, and mentions ADA Title II.
- **Remediation:** a separate product, **e-508**, handles PDF and Office document remediation with AI-assisted options. The *AI Remediation Options* page describes three tiers:
  - Level 1: foundational, with OCR for scans, aimed at internal or archival material, and no guarantee of conformance.
  - Level 2: AI image descriptions and better structure analysis. The page states both a "guaranteed minimum of 95% compliance per page" and a "target compliance level greater than 95%", measured with iAccessible's Assessment Tool against Section 508, PDF/UA, and WCAG 2.1 AA. These are two different commitments, and the page uses both.
  - Level 3: Level 2 plus professional human review and remediation.
- **Accessibility Assistant:** a Q&A assistant on standards. It does not scan.
- **Hosting:** "hosted on secure AWS / FedRAMP servers". This describes the hosting infrastructure. I found no FedRAMP Marketplace listing for iAccessible itself **[unverified]**. No on-premises option is advertised.
- **Customers:** the user reports wide use in the Department of Education. I could not confirm this from public sources (searches of procurement and news records returned nothing). **[unverified]**
- **Pricing:** not published.

**What iAccessible is good at:** site-wide PDF discovery and inventory, assessment scoring, reporting and tracking aimed at government programs, and a service ladder from AI-only to human-reviewed.

**Where a local, open-source tool can compete or complement it:**

1. **Data location.** iAccessible is cloud-hosted. Agencies that cannot send documents off-premises (CUI, FERPA records, pre-decisional drafts, or air-gapped networks) need a local engine.
2. **Transparency of the "95%" metric.** The percentage comes from iAccessible's own assessment tool. An open tool can publish its exact rules, map them to Matterhorn failure conditions and WCAG success criteria, and show veraPDF output, so the score can be audited.
3. **Remediation at scale without per-page fees.** Tiered AI remediation priced per page or document is the norm in this market. A free local engine changes the cost structure for large backlogs.
4. **Complement, not only compete:** accept an inventory list (CSV/JSON of URLs and files) from any scanner, iAccessible included, remediate the files locally, and export results back. iAccessible's export formats have not been confirmed and need checking with a real account. **[unverified]**

### 2.2 Adobe Acrobat Pro and the PDF Services Auto-Tag API

- **Acrobat Pro:** the de facto desktop baseline. It includes auto-tag, a reading order tool, a tags panel, and a built-in accessibility checker. Roughly $240/year per seat (third-party figure). Reviewers describe it as heavily manual for complex documents and best for spot fixes and final review. Desktop only. Cloud features depend on Adobe services.
- **Auto-Tag API:** tags native and scanned PDFs (titles, headings, paragraphs, figures, lists, tables, reading order). Billed at **10 Document Transactions per page**; the free tier is 500 transactions per month, which is about 50 pages ([Adobe licensing](https://developer.adobe.com/document-services/docs/overview/pdf-accessibility-auto-tag-api/dcserviceslicensing)). Cloud only, so documents leave the premises. Used as the tagging engine by several open-source projects (ASU/AWS PDF_Accessibility, and pdf-accessibility-remediator).
- **Implication:** Adobe sets the market expectation for auto-tag quality. An optional adapter for the Auto-Tag API is useful for organizations that already license it, but it must never be required.

### 2.3 CommonLook (Allyant)

- Long-established specialist in PDF remediation. Historically a Windows plugin for Acrobat, with strong table and tag-tree tooling and validation reports.
- July 2025: launched a **web-based CommonLook with AI auto-tagging** ("predictive machine learning"), with simplified and advanced editors, and a validation report per file ([Allyant](https://allyant.com/company-news/allyant-announces-the-launch-of-its-ai-powered-pdf-remediation-software/)) **[vendor]**.
- Pricing: one competitor (RemeDocs) claims about $900+ per seat per year plus an Acrobat licence **[unverified; competitor claim]**.

### 2.4 PREP (Continual Engine)

- Cloud and AI based. Automatic zone, reading-order, and tag detection, a screen-reader preview, an accessibility checker, and manual correction of order and tags ([Stanford UIT](https://uit.stanford.edu/service/prep)).
- Stanford replaced Equidox with PREP as its preferred tool (Stanford UIT news).
- Claims to "automatically tag over 90% of PDFs within seconds" and "95% accuracy" **[vendor; no independent validation found]**.

### 2.5 Equidox

- Web-based, with automated zone detection and a visual editor. Reviewers say it works best on PDFs generated from Word or Google Docs and struggles with scanned or heavily designed documents **[third-party review]**. Also offers HTML export. Pricing not found.

### 2.6 axes4: axesPDF, axesWord, PAC, axesCheck

- **axesPDF:** Windows desktop editor checking against PDF/UA-1, WCAG, and Section 508. Its report covers 89 machine-checkable conditions. Sold by subscription. Its product page lists PDF/UA-1 only; PDF/UA-2 support was not found **[unverified]**.
- **axesWord:** a Word add-in that exports PDF/UA directly from Word. This is the "fix at source" approach.
- **PAC (PDF Accessibility Checker):** free, **Windows only, GUI only**, with no command line found. Checks Matterhorn and WCAG and includes a screen-reader preview. PAC 2026 appears to be the newest release. Because it cannot be scripted, it cannot be used in CI. The plan treats it as an optional manual cross-check.
- **axesCheck:** web version of the checker.

### 2.7 PDFix

- SDK (C++, C#, Java, Python on PyPI as `pdfix-sdk`, proprietary licence) plus a desktop editor, CLI, and Docker pipeline. AI auto-tagging, veraPDF validation, runs fully on-premises **[vendor/third-party review]**. The free "Lite" desktop is a checker. Pricing sources conflict: €490 entry (GetApp), "$599/user/year" (CTO Club), or quote-only (FitGap).
- **Implication:** PDFix is the closest commercial analogue to "local, scriptable, automatable". Its SDK is proprietary, so it cannot be a core dependency of an Apache-2.0 project. It could be an optional adapter.

### 2.8 Others

- **EqualWeb PDF:** 80+ automated checks, AI remediation, expert remediation, and an in-browser accessible viewer **[vendor]**.
- **Foxit PDF Editor:** has an accessibility checker; less specialised.
- **ABBYY FineReader:** strong OCR, and can produce tagged PDFs. OCR-led rather than remediation-led.
- **DocAccess:** produces an accessible HTML transcript served alongside the original. It does not repair the PDF. This is a different compliance strategy, and conformance under Title II depends on how the HTML alternative is offered.
- **Grackle (AbleDocs):** fixes at source in Google Docs, Sheets, and Slides.

## 3. Open-source landscape

| Project | What it offers | Limits |
|---|---|---|
| **veraPDF** (PDF Association / Dual Lab) | Reference validator for PDF/A, PDF/UA-1, PDF/UA-2, WTPDF. CLI, REST, Java library. MPL/GPL dual licence. v1.28.2 confirmed working in spike 001. | Validation only. Cannot judge semantics (spike 001 showed a wrong file passing). Requires Java. |
| **OpenDataLoader PDF** (Hancom), v2.5.12 | Apache-2.0. Layout analysis, XY-Cut++ reading order, table detection, and **auto-tagging to Tagged PDF**. Python/Node/Java SDK and CLI. Local. Built with Dual Lab (veraPDF) on Well-Tagged PDF. Optional "hybrid" AI backend (docling-based) for OCR, complex tables, and image descriptions. | **PDF/UA-1/2 export and its visual "accessibility studio" are paid enterprise add-ons.** Requires Java 11+. In spike 001 its output lacked document-level PDF/UA requirements and used placeholder alt text. |
| **Docling** (IBM / LF AI) | MIT. Layout, TableFormer tables, OCR integration, reading order, DocTags. granite-docling-258M VLM is Apache-2.0. | An extraction framework, not a PDF writer. Does not tag PDFs. |
| **OCRmyPDF** | MPL-2.0. Adds an OCR text layer and produces PDF/A. Tesseract by default, with plugins for EasyOCR, PaddleOCR, and Apple Vision. | The text layer is **not tagged**, so it is a first step only. Depends on Ghostscript (AGPL) as an external program. |
| **PAVE 2.0** (ZHAW, research) | Step-by-step remediation UI. A CHI 2025 study found tag accuracy scores of 80.1% (experienced users) and 75.2% (novices), against 42.0% and 39.2% with Acrobat Pro ([ACM](https://dl.acm.org/doi/full/10.1145/3706598.3713084)). | Research prototype. Useful as **evidence that guided UX roughly doubles tag accuracy over Acrobat**, which supports investing in the reviewer UI. |
| **ASU / AWS PDF_Accessibility** | MIT. Adobe Auto-Tag API plus Amazon Bedrock alt text, on Step Functions, Lambda, and Fargate. Used by Ohio State Libraries. | Cloud-bound and requires paid Adobe credentials. Not local. |
| **CUNY AI Lab pdf-accessibility-app**, **pdf-accessibility-remediator**, **accesspdf**, **Pdf-Acc-Toolset** | Small projects combining OCR, structure, LLM alt text, and veraPDF validation. | Early stage, single maintainers. Maintenance status unverified. Good sources of design ideas, not dependencies. |

## 4. Evidence on accuracy (what independent research says)

- **Checkers cannot verify tag correctness.** A 2024 study read 133 scholarly PDFs with NVDA and VoiceOver and found that checkers confirm tags exist but not whether they are correct ([arXiv 2410.03022](https://arxiv.org/pdf/2410.03022)).
- **LLMs help with the semantic judgments rule-based tools cannot make**, but are imperfect. A 2025 benchmark found GPT-4-Turbo reached 0.85 overall accuracy on PDF accessibility criteria, with all models weak on "Not Present" and "Cannot Tell" labels, especially for alt-text quality. It also reported that PAC 2024 and axesPDF tend toward false negatives, and that rule-based checkers miss wrong header-to-data relationships ([arXiv 2509.18965](https://arxiv.org/html/2509.18965)). That paper's dataset is a candidate for our evaluation harness (licence to be checked).
- **Guided remediation UX matters more than raw automation** (PAVE 2.0, above).
- **Spike 001 (this repo)** reproduces the core finding locally: a file with swapped heading/paragraph roles, reversed reading order, and alt text "image" passes veraPDF PDF/UA-1.

Implication: vendor claims of "90-95% automatic" should be read as "passes the vendor's machine checks". The differentiator worth building is **semantic QA plus efficient human verification**, with an honest, auditable record of what was checked by machine, by AI, and by a person.

## 5. Strengths to combine, and where this project should differ

| Strength seen in market | Who does it well | How this project adopts it |
|---|---|---|
| Site-wide PDF discovery, inventory, and backlog scoring | iAccessible, Siteimprove | Crawler and inventory import, plus Title II exception triage (Phase 5) |
| Fast auto-tagging | PREP, Adobe API, CommonLook web, OpenDataLoader | OpenDataLoader as the default local engine. Adobe/PDFix as optional adapters. |
| Strong tag-tree and table editors | CommonLook, axesPDF, Acrobat | Web reviewer workstation focused on tables, reading order, and figures (Phase 4) |
| Screen-reader preview | PREP, PAC | Linearised reading-order preview generated from the structure tree, plus optional local TTS |
| Fix at source | axesWord, Grackle | Later phase: DOCX checks and guidance, and "return to author" outcome |
| Service tiers (AI only to human-reviewed) | iAccessible, Accessibility on Demand | Policy-driven lanes: auto, AI-assisted, human-required. The tool never claims conformance without a recorded human verification. |
| Validation reports | All | veraPDF + Matterhorn + WCAG mapping + semantic QA + human verification log, in HTML, JSON, and CSV |

**Positioning in one sentence:** a local-first, auditable, open-source remediation engine and reviewer workstation that turns auto-tagged output into verifiably accessible PDF/UA documents, with optional, policy-controlled AI, priced at zero for the software.

## 6. Open questions to resolve with real accounts or trials

1. iAccessible export formats (to support an import/export bridge) and how its "95%" is computed.
2. Head-to-head quality on a shared corpus: OpenDataLoader (+hybrid), Adobe Auto-Tag, PDFix, PREP, CommonLook web. This needs trial licences, and the vendors' terms may forbid publishing benchmarks.
3. Whether PAC 2026 added a command line or PDF/UA-2 support.
4. axesPDF PDF/UA-2 support.
