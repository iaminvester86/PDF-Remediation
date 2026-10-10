# PDF-Remediation

An open-source (Apache-2.0), local-first application that makes PDFs accessible to people who use screen readers and other assistive technology. It:

- recognises text on scanned pages (OCR)
- tags each document's structure (headings, paragraphs, lists, tables, figures, links, form fields)
- sets the title and language
- validates the result against PDF/UA-1 with veraPDF and its own semantic checks
- writes a report for each file

A person then reviews alt text and anything the tool was unsure about in an accessible web interface.

Everything runs on your own computer or server. Documents are never sent anywhere unless you turn on an AI provider that is outside your network.

**Status: 0.1, working prototype.** It handles common born-digital and scanned documents. It is not yet evaluated on a large real-world corpus. Read [What is missing](#what-is-missing-and-needs-work) before using it on documents that matter.

## Contents

- [What it does](#what-it-does)
- [Install](#install)
- [Use it](#use-it)
- [Engines: OCR, structure, validation](#engines-ocr-structure-validation)
- [Configuration](#configuration)
- [AI suggestions (optional)](#ai-suggestions-optional)
- [Security](#security)
- [What is missing and needs work](#what-is-missing-and-needs-work)
- [Development](#development)

## What it does

You can add work in any combination of:

- **multiple PDF files**, or zip archives of PDFs
- **whole folders**, including subfolders (other file types are ignored)
- **links**: a link to a PDF fetches that file; a link to a web page fetches the PDFs that page links to on the same site

Each file then goes through these steps:

1. **Inspect:** count pages and detect existing tags, encryption, digital signatures (remediation invalidates them, so the report warns), and XFA forms (these cannot be made PDF/UA).
2. **OCR, only where needed:** a page with almost no extractable text that is mostly covered by images is treated as a scan. Its text is recognised and added as an invisible layer, so the page looks exactly the same but its text can now be read, searched and tagged. Pages that already have text are not touched. If OCR is turned off or not installed, the report records an error for those pages instead.
3. **Normalise:** remove empty text blocks, add missing Unicode maps from glyph names, and repair broken ones using the file's own ActualText. For example, Chrome maps ligatures to U+0000.
4. **Tag** with one of three engines. In `auto` mode the engine is picked like this:
   - **Already tagged:** good tags are kept. Broken tags are replaced, and existing alt text is carried over.
   - **OCR was applied:** the built-in engine is used, because OpenDataLoader mis-tags OCR text layers ([why](#engines-ocr-structure-validation)).
   - **Otherwise:** OpenDataLoader if it is installed, else the built-in engine.
5. **Finish:** document title, language, `DisplayDocTitle`, tab order, PDF/UA identifier, and bookmarks from headings.
6. **AI suggestions (optional):** draft alt text from a vision model. Drafts go to the reviewer and are not written into the PDF unless you choose that.
7. **Verify:**
   - veraPDF PDF/UA-1 validation.
   - About 20 semantic checks that validators cannot make: placeholder alt text, headings that look like body text, reading order that jumps up the page, bullets not tagged as lists, vague link text, tables without headers, non-embedded fonts.
   - A rendering gate: every page must look identical to the input.
   - A text gate: the extracted text must be unchanged.
8. **Report** in HTML and JSON, plus a `summary.csv` per batch. The status has three parts: **machine validation** (veraPDF), **issues** (mapped to WCAG success criteria and Matterhorn checkpoints), and **human verification**, which stays "not done" until a person reviews the file. The tool never calls a document "compliant".

## Install

Requirements:

- **Python 3.11 or newer.**
- **Java 11 or newer, recommended.** Java 17 or 21 (for example [Eclipse Temurin](https://adoptium.net)) enables the veraPDF validator and the OpenDataLoader engine.

Without Java the app still works with the built-in engine, but reports say "Machine validation: Not run".

### One command (recommended)

```bash
scripts/install.sh                                         # Linux / macOS, installs into ./.venv
powershell -ExecutionPolicy Bypass -File scripts\install.ps1   # Windows
```

The script:

1. creates a virtual environment;
2. installs the app with Python OCR and OpenDataLoader (`pip install -e ".[all]"`);
3. downloads veraPDF if Java is present (`pdfrem install-engines`);
4. runs `pdfrem doctor`, which shows what is ready.

### By hand

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[all]"            # app + RapidOCR (Python OCR) + OpenDataLoader
pdfrem install-engines             # veraPDF validator, needs Java 11+
pdfrem doctor
```

Optional extras, if you do not want everything:

| Extra | Adds |
|---|---|
| `ocr` | RapidOCR on ONNX Runtime, the default OCR engine |
| `odl` | OpenDataLoader structure engine (Java) |
| `tesseract` | `pytesseract`, the alternative OCR engine. You also need the `tesseract` program and its language packs. |
| `all` | `ocr` and `odl` |
| `dev` | pytest and reportlab, for the test suite |

`pdfrem install-engines` downloads the 19 veraPDF 1.28.2 jars directly from Maven Central and checks each one against a pinned SHA-256. No Maven or manual download is needed. The jars go to `~/.pdfrem/engines/verapdf` (change this with `PDFREM_ENGINES_DIR`). Running it again only re-downloads missing or damaged files. If you already have the official veraPDF installer, set `PDFREM_VERAPDF_CMD` to its launcher instead.

### Docker

```bash
docker build -t pdf-remediation .
docker run -p 8765:8765 -v pdfrem-data:/data -e PDFREM_ACCESS_TOKEN=change-me pdf-remediation
```

The image contains Python, a Java runtime, RapidOCR, OpenDataLoader and veraPDF. It contains no AI model. The Dockerfile has not yet been built in CI.

## Use it

### Web app

```bash
pdfrem serve                       # then open http://127.0.0.1:8765/
```

1. Choose PDF or zip files, a folder, and/or paste links (one per line).
2. Choose the document language, structure engine, OCR setting (automatic by default) and what to do with files that are already tagged. Then select **Start remediation**.
3. The job page updates as files finish. Open a file to:
   - see its status, issues, heading outline, OCR summary and safety checks;
   - **review figures**: write alt text or mark an image decorative, then save. This updates the PDF and validates it again.
   - download the remediated PDF, the HTML or JSON report, or the original.
4. **Download all results (zip)** returns every PDF and report in the original folder structure, plus `summary.csv`.

The home page lists which components are installed. The interface works with a keyboard and without JavaScript, and it announces progress to screen readers. axe-core (WCAG 2.2 AA and best-practice rules) reports 0 violations on the home, job and file pages. That is an automated check, not a substitute for testing with screen reader users.

### Command line

```bash
pdfrem remediate report.pdf ./policies/ https://www.example.gov/forms/ -o remediated/
pdfrem remediate ./archive --workers 4 --lang es-US        # parallel; Spanish as default language
pdfrem remediate ./scans --ocr off                         # never OCR (scanned pages are reported)
pdfrem remediate ./reports --engine basic                  # force the built-in engine
pdfrem validate remediated/report.pdf                      # check only; changes nothing
pdfrem doctor                                              # what is installed
```

Output mirrors the input structure (`remediated/policies/2025/x.pdf`, with `x.report.html` and `x.report.json` beside it), plus `summary.csv`. `summary.csv` includes the pages that were OCR'd.

Exit codes:

| Code | Meaning |
|---|---|
| `0` | every file is ready for review |
| `1` | some files need attention |
| `3` | some files failed |
| `2` | there was nothing to do |

## Engines: OCR, structure, validation

### OCR (Python)

| Engine | Install | Notes |
|---|---|---|
| **RapidOCR** (default) | `pip install -e ".[ocr]"` | Apache-2.0. PaddleOCR (PP-OCRv6) models on ONNX Runtime. The models ship inside the wheel, so it works offline with no system packages. |
| **Tesseract** | `pip install -e ".[tesseract]"` plus the `tesseract` program | Uses the document language to pick a language pack. Use it for scripts the RapidOCR model handles poorly. |

`PDFREM_OCR_ENGINE` selects the engine: `auto` (the default) uses RapidOCR when it is installed, then Tesseract.

How the text layer works:

- Recognised lines are written in text render mode 3 (invisible) with a small embedded "glyphless" font. Each line is scaled to the width of the words in the image.
- On rotated pages, lines follow the orientation of the displayed page.
- The rendering gate confirms that OCR'd pages still look exactly like the scan.
- The scan image itself becomes a background artifact, so the recognised text is what gets tagged.

What was measured in this environment (4-vCPU container, synthetic scans rendered from born-digital pages):

- **Recognition:** sample pages were recognised with a mean confidence of 0.99. Spanish, French and German accented text came through correctly.
- **Validation:** OCR'd documents pass veraPDF PDF/UA-1, with H1 and H2 headings detected from the recognised text.
- **Speed:** about 1.6 to 2.3 seconds per page at 150 to 300 dpi, for sparse pages of about 8 lines. Dense pages take longer.

Real scans are skewed, noisy or low resolution, and recognition quality on them has **not** been measured yet.

Lines below `PDFREM_OCR_MIN_CONFIDENCE` (0.3) are dropped. Pages with a mean confidence below 0.85 get a "proofread this page" warning. Every OCR'd file gets an info issue asking for proofreading.

### Structure engines

| | Built-in engine (Python) | OpenDataLoader (Java, Apache-2.0) |
|---|---|---|
| Install | always available | `pip install -e ".[odl]"` plus Java 11+ |
| Headings, paragraphs, lists, figures | yes (font-size and layout heuristics) | yes (layout analysis) |
| Links | yes | yes |
| Form fields, other annotations | yes | not tested |
| Running headers, footers, page numbers | marked as artifacts | marked as artifacts |
| Ruled tables (drawn cell borders) | yes: header rows, `ColSpan`, `RowSpan`, `Scope` | yes: header rows, `ColSpan`, `RowSpan`, `Scope` |
| Borderless tables (columns aligned by spacing) | yes, with guards against two-column prose | not detected in our test |
| OCR'd pages | yes; the scan image becomes background | tags the scan as a figure and changes the text layer, so `auto` does not use it there |

**Tables in the built-in engine:**

- **Ruled tables** are found from the drawn grid lines. A missing internal border merges cells (`ColSpan` across, `RowSpan` down).
- **Header rows:** the top row is the header. The header extends down when a top-row cell spans rows, or when a cell groups sub-headings under it.
- **Borderless tables** need three or more rows whose text falls into the same column bands. Cells must be short, and at least one column must hold short values such as numbers, codes or labels. This keeps two-column articles from being tagged as tables.
- Every tagged table raises a "check the headers" warning, because header detection is an assumption.
- Aligned columns that do not meet the rules are left as text, with a "possible table" warning for the reviewer.

**How the two engines compared:** we ran both on four synthetic test tables (ruled 4×3; ruled with a two-row header, a row span and a column span; borderless 5×3; and a two-column prose control). All outputs pass veraPDF, with identical rendering and text.

| Test table | Built-in engine | OpenDataLoader |
|---|---|---|
| Ruled 4×3 | correct | correct |
| Ruled with a two-row header | correct | spans correct, but the FY2025 and FY2026 sub-headings tagged as data cells (`TD`) |
| Borderless 5×3 | correct | did not detect the table |
| Two-column prose (control) | correctly not a table | correctly not a table |

Four synthetic tables are too few to say either engine is better in general. Real documents (scanned tables, tables spanning pages, nested tables) are where the comparison needs to be made. `auto` prefers OpenDataLoader for born-digital files because its general layout analysis is the more mature of the two. That preference is a judgment, not a measurement. Use `--engine basic` (or the web form) to choose the built-in engine for a batch.

### Validation (Java)

veraPDF runs as a separate process for each file, using the PDF/UA-1 profile. If it is not installed, files still get the semantic checks and the rendering and text gates, but machine validation is reported as "Not run". It is never reported as passed.

## Configuration

Every setting can be set as an environment variable, `PDFREM_<NAME>`:

| Variable | Default | Meaning |
|---|---|---|
| `PDFREM_DATA_DIR` | `./pdfrem-data` | Where web jobs are stored |
| `PDFREM_HOME` | `~/.pdfrem` | Base folder for downloaded engines |
| `PDFREM_ENGINES_DIR` | `$PDFREM_HOME/engines` | Where `install-engines` puts veraPDF |
| `PDFREM_DEFAULT_LANG` | `en-US` | Language written when a file declares none |
| `PDFREM_ENGINE` | `auto` | Structure engine: `auto`, `basic` or `odl` |
| `PDFREM_OCR_ENGINE` | `auto` | `auto`, `rapidocr` or `tesseract` |
| `PDFREM_OCR_DPI` | `200` | Resolution used to render pages for OCR |
| `PDFREM_OCR_MIN_CONFIDENCE` | `0.3` | Recognised lines below this confidence are dropped |
| `PDFREM_JAVA_CMD` | `java` | Java executable |
| `PDFREM_VERAPDF_CMD` | none | Launcher from the official veraPDF installer (optional; overrides the downloaded jars) |
| `PDFREM_VERAPDF_TIMEOUT` | `300` | Seconds before a validation run is stopped |
| `PDFREM_WORKERS` | half the CPUs, max 4 | Parallel worker processes |
| `PDFREM_MAX_FILE_MB`, `PDFREM_MAX_PAGES`, `PDFREM_MAX_FILES_PER_JOB` | 200, 3000, 2000 | Limits |
| `PDFREM_ALLOW_PRIVATE_URLS` | off | Allow links to internal hosts (intranet use) |
| `PDFREM_AI_ENABLED`, `PDFREM_AI_BASE_URL`, `PDFREM_AI_MODEL`, `PDFREM_AI_API_KEY`, `PDFREM_AI_ALLOW_REMOTE` | off; Ollama on localhost | AI settings |
| `PDFREM_ACCESS_TOKEN` | none | Token required by the web app. One is generated automatically when serving on a non-local address. |

## AI suggestions (optional)

AI is off unless you enable it. One adapter speaks the OpenAI-compatible protocol, which covers Ollama, llama.cpp, vLLM and LM Studio on your own machine, as well as many hosted services:

```bash
ollama pull qwen2.5vl:7b
PDFREM_AI_ENABLED=1 pdfrem serve
```

- **Local by default:** only endpoints on this computer or a private network are allowed. Sending page images anywhere else requires `PDFREM_AI_ALLOW_REMOTE=1` (plus `PDFREM_AI_API_KEY` if the service needs one).
- **Guarded inputs and outputs:** document text sent as context is fenced as untrusted data, outputs are parsed as JSON, and the model gets no tools.
- **Audited:** every call is recorded in the report with the endpoint, model, image hash and latency.

Cloud sign-in (Entra ID, AWS SSO, Google ADC) and official-CLI bridges are planned. [`docs/research/05`](docs/research/05-ai-integration-and-government-constraints.md) explains why reusing consumer CLI login tokens is not supported.

## Security

- **Local binding:** the server listens on `127.0.0.1` by default. Serving on any other address requires an access token. If you do not set one, a token is generated and printed. Multi-user sign-in (OIDC or SAML) is planned, not built.
- **Link fetching:** every link is checked before each request and each redirect, and internal addresses are blocked unless you allow them. A hostile DNS server could still answer differently between the check and the connection (DNS rebinding), so shared deployments should sit behind an egress proxy.
- **Uploads:** zip extraction blocks path traversal and enforces size limits. Uploaded files must start with a PDF header.
- **Isolation:** PDF parsing runs in separate worker processes. Pages are served with a strict Content-Security-Policy.
- **Engine downloads:** the engine installer verifies every jar against a pinned SHA-256 before using it.

## What is missing and needs work

These are known gaps, listed so nobody mistakes the prototype for a finished product. They are tracked in [`docs/PLAN.md`](docs/PLAN.md).

**Accuracy and evaluation**

- **No large-scale evaluation yet.** The test suite uses synthetic documents. Real-world checks so far are a 6-file smoke test (all pass veraPDF after remediation). The plan calls for a labelled corpus of at least 200 government documents with measured heading, table, list and reading-order accuracy before any accuracy claims are made.
- **Heuristics make mistakes.** Every file needs the human review the report asks for.

**OCR**

- **Not tested on real-world scans.** Recognition quality on skewed, noisy, low-resolution or handwritten scans is unmeasured. There is no deskewing or image clean-up step.
- **Pages that mix text and a scanned region are not OCR'd.** A page with 20 or more extractable characters is treated as having text, so a scanned picture of a paragraph on an otherwise digital page is not recognised.
- **Rotated pages:** OCR'd text on rotated pages is extractable and correctly placed, but heading and list detection works in unrotated page space. Rotated pages therefore get paragraphs, not headings.
- **Language coverage:** the default RapidOCR model handled English, Spanish, French and German in our tests. Other languages and scripts are untested. Use Tesseract with the right language pack for them.
- **No word-level review:** there is no screen for proofreading OCR text, and no per-word confidence in the report. Confidence is reported per page.

**Tables**

- **Not detected:**
  - row headers (a first column of `TH` with `Scope=Row`);
  - nested tables;
  - tables split across pages.
- **Expected to fail (untested):**
  - borderless tables whose cells wrap onto several lines, because each baseline is read as a row;
  - tables drawn with shaded row bands instead of lines.
- **No table editor:** there is no editor to correct headers or spans by hand. The reviewer can only see the warning.

**Structure and content**

- **Reading order:** complex multi-column reading order follows content-stream order, and there is no reading-order editor.
- **Lists:** nested lists are not detected.
- **Form XObjects:** content inside them is tagged as a single unit. Content re-marking (plan WP 2.2) is not built.
- **Fonts:** fonts that are not embedded cannot be fixed. The report says to re-export from the source.
- **Not built yet:** PDF/UA-2, MathML, and fixes in Office source documents.

**Product and operations**

- **Not built:**
  - heading, reading-order and table editors;
  - a screen-reader preview;
  - multi-user sign-in and roles;
  - cloud AI sign-in;
  - signed policy profiles.
- **Validation speed:** veraPDF starts a new Java process for each file. That took about 1.8 seconds for a one-page file here, most of it Java start-up. A persistent validation service is planned.
- **Not yet verified:**
  - CI has not run on GitHub yet;
  - the Docker image has not been built;
  - `scripts/install.ps1` has not been run on Windows.

  (`scripts/install.sh` was run end to end on Linux.)
- **Not packaged yet:** there is no Windows installer, air-gapped bundle, SBOM or signed release.

## Development

```bash
pip install -e ".[dev,all]" && pdfrem install-engines
pytest                         # tests that need veraPDF or an OCR engine skip when it is missing
```

Package layout (`src/pdf_remediation/`):

| Path | Purpose |
|---|---|
| `pipeline.py` | Per-file flow: inspect, OCR, normalise, tag, finish, AI, verify, report |
| `inputs/` | Files, folders, zip archives, links (`links.py`), and the SSRF guard (`netguard.py`) |
| `ocr/` | Detecting pages that need OCR, engine adapters (`engines.py`), and the invisible text layer (`textlayer.py`) |
| `pdf/` | Low-level PDF work: PDFium geometry, content-stream scanning, structure-tree reading, Unicode repair, finisher, figure edits |
| `tagging/` | Structure engines: built-in (`basic.py` with `layout.py`, `tables.py`, `writer.py`), OpenDataLoader (`odl.py`), and keep-or-retag logic for tagged files (`existing.py`) |
| `checks/` | veraPDF (`verapdf.py`), semantic checks (`semantic.py`), rendering and text gates (`gates.py`) |
| `java.py` | Java detection and the checksum-verified veraPDF installer |
| `status.py` | Component status shown by `pdfrem doctor` and the web app |
| `jobs.py`, `web/` | Batch runner and web interface (FastAPI, Jinja templates, no build step) |
| `report.py`, `issues.py` | Reports and the issue model (WCAG and Matterhorn mapping) |
| `ai.py`, `config.py`, `cli.py` | AI adapter, settings, command line |

CI runs the tests on Linux and Windows with Python 3.11 and 3.13, plus a licence gate that fails on any GPL or unknown licence in the core and OCR dependency closure. veraPDF (GPL/MPL) runs as a separate program and is not linked into the app.

## Planning documents

- [`docs/PLAN.md`](docs/PLAN.md): plan of action, decisions, phases, risk register, implementation status.
- [`docs/research/`](docs/research/): source-document review, competitive landscape, standards, licensing, AI and government constraints.
- [`spikes/001-tagging-feasibility/`](spikes/001-tagging-feasibility/): the experiment that shaped the design.
