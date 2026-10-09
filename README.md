# PDF-Remediation

An open-source (Apache-2.0), local-first application for making PDFs accessible. It tags PDFs for screen readers (PDF/UA-1), checks them with the veraPDF validator and its own semantic checks, and gives each file a report. A reviewer then confirms alt text, headings and reading order in an accessible web interface.

Add work in any combination of:

- **multiple PDF files**, or zip archives of PDFs
- **a whole folder** (subfolders included; other file types are ignored)
- **links**: a link to a PDF fetches that file, and a link to a web page fetches the PDFs it links to on the same site

Status: **0.1, working prototype** of Phases 1 to 4 of [`docs/PLAN.md`](docs/PLAN.md). Read [Limitations](#limitations) before using it on documents that matter.

## Quick start

Requirements: Python 3.11+. Java 11+ is recommended, because it enables the veraPDF validator and the OpenDataLoader engine.

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[odl]"            # core + OpenDataLoader structure engine (needs Java)
scripts/fetch-verapdf.sh           # downloads the veraPDF validator (needs Java + Maven)
pdfrem doctor                      # shows which optional parts are installed
pdfrem serve                       # open http://127.0.0.1:8765/
```

Without Java the app still works using the built-in engine, but files are not validated by veraPDF. The report then says "Machine validation: Not run".

### Web app

1. Choose PDF or zip files, a folder, and/or paste links (one per line).
2. Pick the document language and options, then select **Start remediation**.
3. The job page updates as files finish. Open a file to:
   - **review figures**: write alt text or mark an image decorative, then save, which updates the PDF and re-validates it
   - read the issues list (mapped to WCAG success criteria and Matterhorn checkpoints)
   - download the remediated PDF, the HTML/JSON report, or the original
4. **Download all results (zip)** returns every PDF and report in the original folder structure, plus `summary.csv`.

The interface was checked with axe-core (0 violations on every page). It works with the keyboard, without JavaScript, and announces progress to screen readers.

### Command line

```bash
pdfrem remediate report.pdf ./policies/ https://www.example.gov/forms/ -o remediated/
pdfrem remediate ./archive --workers 4 --lang es          # parallel, Spanish default language
pdfrem validate remediated/report.pdf                     # check without changing anything
```

Output mirrors the input structure (`remediated/policies/2025/x.pdf`, with `x.report.html` and `x.report.json` next to it) plus `summary.csv`. Exit codes: `0` all ready for review, `1` some need attention, `3` some failed, `2` nothing to do.

## What it does to each file

1. **Inspect:** page count, existing tags, encryption, signatures (warns that remediation invalidates them), XFA forms (cannot be made PDF/UA), scanned pages.
2. **OCR** image-only pages when OCR is installed (`pip install -e ".[ocr]"` plus Tesseract and Ghostscript).
3. **Normalise:** remove no-op text blocks, add missing Unicode maps from glyph names, and repair invalid Unicode maps (for example Chrome's ligatures mapped to U+0000) using the file's own ActualText.
4. **Tag:**
   - **OpenDataLoader** (automatic default when installed): layout analysis that also finds tables.
   - **Built-in engine:** headings by font size, paragraphs, bullet and numbered lists, figures, links, form fields, and running headers/footers and page numbers as artifacts.
   - **Files that are already tagged:** good tags are kept. Broken ones are replaced, and any existing alt text is carried over.
5. **Finish:** document title, language, `DisplayDocTitle`, tab order, PDF/UA identifier, bookmarks from headings.
6. **AI suggestions** (optional): alt text from a local vision model. Suggestions are pre-filled for review, not written into the PDF unless you choose to.
7. **Verify:**
   - veraPDF PDF/UA-1 validation
   - semantic checks that validators cannot make: placeholder alt text, headings that look like body text, reading order that jumps back up the page, bullets not tagged as lists, vague link text, tables without headers, non-embedded fonts
   - a rendering gate: every page must look identical to the original
   - a text gate: the extracted text must be unchanged
8. **Report:** a three-part status. *Machine validation* (veraPDF), *issues*, and *human verification*, which is always "not done" until a person reviews the file. The tool never claims a document is "compliant".

## AI (optional, local by default)

AI is off unless enabled. One adapter speaks the OpenAI-compatible protocol, which covers Ollama, llama.cpp, vLLM and LM Studio on your own machine, and many hosted services:

```bash
ollama pull qwen2.5vl:7b
PDFREM_AI_ENABLED=1 pdfrem serve
```

- By default only endpoints on this computer or a private network are allowed. Sending page images anywhere else requires `PDFREM_AI_ALLOW_REMOTE=1` (and `PDFREM_AI_API_KEY` if needed).
- Document text sent as context is fenced as untrusted data, outputs are parsed as JSON, and the model gets no tools.
- Every call is recorded in the report: endpoint, model, image hash, latency.

Cloud sign-in (Entra ID, AWS SSO, Google ADC) and official-CLI bridges are planned. [`docs/research/05`](docs/research/05-ai-integration-and-government-constraints.md) explains why reusing consumer CLI login tokens is not supported.

## Configuration

Every setting can be set as an environment variable, `PDFREM_<NAME>`:

| Variable | Default | Meaning |
|---|---|---|
| `PDFREM_DATA_DIR` | `./pdfrem-data` | Where web jobs are stored |
| `PDFREM_DEFAULT_LANG` | `en-US` | Language written when a file has none |
| `PDFREM_ENGINE` | `auto` | `auto`, `basic` or `odl` |
| `PDFREM_VERAPDF_CMD` / `PDFREM_VERAPDF_LIB` | `vendor/verapdf/lib` | veraPDF launcher, or folder of jars |
| `PDFREM_WORKERS` | half the CPUs, max 4 | Parallel worker processes |
| `PDFREM_MAX_FILE_MB`, `PDFREM_MAX_PAGES`, `PDFREM_MAX_FILES_PER_JOB` | 200, 3000, 2000 | Limits |
| `PDFREM_ALLOW_PRIVATE_URLS` | off | Allow links to internal hosts (intranet use) |
| `PDFREM_AI_ENABLED`, `PDFREM_AI_BASE_URL`, `PDFREM_AI_MODEL`, `PDFREM_AI_API_KEY`, `PDFREM_AI_ALLOW_REMOTE` | off, Ollama on localhost | AI settings |
| `PDFREM_ACCESS_TOKEN` | none | Required token for the web app (generated automatically when serving on a non-local address) |

## Security notes

- The server binds to `127.0.0.1` by default. Serving on another address requires an access token, which is generated and printed if you don't set one. Multi-user sign-in (OIDC/SAML) is planned, not built.
- Links are checked before every request and redirect. Internal addresses are blocked unless allowed. A hostile DNS server could still answer differently between the check and the connection (DNS rebinding), so shared deployments should sit behind an egress proxy.
- Zip extraction blocks path traversal and enforces size limits. Uploads must start with a PDF header.
- PDF parsing runs in separate worker processes, and pages are served with a strict Content-Security-Policy.

## Limitations

These are known gaps, tracked in [`docs/PLAN.md`](docs/PLAN.md):

- **The built-in engine does not detect tables** (it flags likely tables for review), nested lists, or complex multi-column reading order beyond content order. Use the OpenDataLoader engine for those, and review.
- **Content inside form XObjects** is tagged as one unit. Content re-marking for such cases (plan WP 2.2) is not built.
- **Fonts that are not embedded cannot be fixed;** the report tells you to re-export from the source.
- **OCR is wired in but was not exercised in this build environment** (Tesseract was unavailable).
- **PDF/UA-2, MathML, Office source fixes, the reading-order and table editors, multi-user sign-in, and cloud AI sign-in** are later phases.
- **Heuristics make mistakes.** Every file still needs the human review the report asks for.

## Development

```bash
pip install -e ".[dev,odl]" && scripts/fetch-verapdf.sh
pytest                         # 25 tests; veraPDF-dependent tests skip if it is not installed
```

Layout: `src/pdf_remediation/` (`tagger.py` built-in engine, `pipeline.py` per-file flow, `qa.py` semantic checks, `verify.py` veraPDF and gates, `fonts.py` Unicode repair, `fetch.py` links, `jobs.py` batch runner, `web.py` + `templates/` UI, `cli.py`).

## Planning documents

- [`docs/PLAN.md`](docs/PLAN.md): plan of action, decisions, phases, risk register.
- [`docs/research/`](docs/research/): source-document review, competitive landscape, standards, licensing, AI and government constraints.
- [`spikes/001-tagging-feasibility/`](spikes/001-tagging-feasibility/): the experiment that shaped the design.
