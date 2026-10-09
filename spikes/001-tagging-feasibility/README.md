# Spike 001: Can a Python-first stack produce PDF/UA output, and what does validation miss?

Date run: 2026-10-09. Run it yourself with `./run.sh` (Python 3.11+, Java 11+, Maven 3, DejaVu fonts).

## Questions

1. Can the core tag-writing step (marked content, structure tree, parent tree, document metadata) be done with pikepdf (MPL-2.0) alone, without a commercial SDK?
2. Does veraPDF, the reference open-source validator, catch semantically wrong tagging?
3. How far does OpenDataLoader PDF's free auto-tagger (Apache-2.0) get on its own, and what has to be added?
4. Is PDF/UA-2 a small extension of the PDF/UA-1 path or a separate one?

## Tool versions

| Tool | Version | License |
|---|---|---|
| pikepdf (qpdf 12.4.2) | 10.16.0 | MPL-2.0 |
| reportlab (sample generation only) | 5.0.1 | BSD |
| opendataloader-pdf | 2.5.12 | Apache-2.0 (needs Java 11+) |
| veraPDF CLI (`greenfield-apps`) | 1.28.2 | GPLv3+ or MPLv2+ |

## Results

### Experiment A: hand-written pikepdf tagger (`spike.py`)

The script rewrites the page content stream, wrapping each text block and image in `BDC ... EMC` with an MCID, marks the footer as a pagination artifact, builds `StructTreeRoot`, `ParentTree`, `MarkInfo`, `Lang`, `DisplayDocTitle`, `/Tabs /S`, and XMP `pdfuaid:part=1`.

| File | Profile | Result | Meaning |
|---|---|---|---|
| `untagged_embed.pdf` | PDF/UA-1 | FAIL (6 rules) | Baseline: untagged input |
| `tagged_noembed.pdf` | PDF/UA-1 | FAIL (7.21.4.1) | Standard-14 Helvetica is not embedded. Tagging cannot fix a font problem. |
| `tagged_embed.pdf` | PDF/UA-1 | **PASS** | Pure-Python tag writing satisfies every machine check for this document |
| `tagged_embed.pdf` | PDF/UA-2 | FAIL (3 rules) | UA-2 needs `pdfuaid:rev`, part=2, and PDF 2.0 structure namespaces |
| `wrong_embed.pdf` | PDF/UA-1 | **PASS** | Heading and paragraph roles swapped, reading order reversed, alt text = "image". The validator cannot see any of it. |

### Experiment B: OpenDataLoader auto-tag, then a finisher (`make_sample.py`, `finish.py`, `strip_empty_bt.py`)

Input is a two-page, two-column document with H1/H2 headings, a bulleted list, a 4x3 table with a header row, a figure with a caption, and a running header and footer.

What OpenDataLoader produced, with no AI backend:

- Correct: H1, H2s, `L/LI/Lbl/LBody`, `Table/TR/TH/TD` with `Scope`, a `Figure`, headers and footers as `/Artifact`, plausible two-column reading order.
- Questionable: the top-left header cell got `Scope /Both` when it only heads its column. The figure caption is a plain `P`, not `Caption`.
- Missing: `MarkInfo`, `Lang`, XMP metadata, `DisplayDocTitle`, a real title. Alt text is the placeholder `"image 1"`.

| Stage | PDF/UA-1 result |
|---|---|
| OpenDataLoader output | FAIL: 6 rule types (MarkInfo, Lang x2, Metadata, DisplayDocTitle, font) |
| + finisher (MarkInfo, Lang, XMP, title, DisplayDocTitle, Tabs) | FAIL: 1 rule (non-embedded Helvetica referenced by text blocks that draw nothing) |
| + removing text blocks that draw no glyphs | FAIL: 1 rule (7.21.4.1-2: the source generator's font subset lacks the glyph used for list bullets) |

## Conclusions used in the plan

1. **Feasible.** Tag writing for PDF/UA-1 is achievable with pikepdf. No commercial SDK is required for the core write path. (Shown for simple content only. Form XObjects, inline images, Type 3 fonts, and existing broken tags are not yet tested; see the risk register in `docs/PLAN.md`.)
2. **A veraPDF PASS is not evidence of accessibility.** The tool needs its own semantic QA layer and a human verification record. It must never report "compliant" on the basis of machine checks alone.
3. **OpenDataLoader is a strong structure detector, but not a finisher.** Its free tier stops at "Tagged PDF". Document-level PDF/UA requirements, real alt text, and font repair are left to the integrator (its PDF/UA export is a paid add-on). That gap is where this project adds value.
4. **Fonts are a separate workstream.** Non-embedded fonts and incomplete subsets are common in real files, and tagging cannot fix them. The tool needs a font-repair module and a "send back to source" outcome for files it cannot repair safely.
5. **PDF/UA-2 is a separate writer path** (PDF 2.0 namespaces, `pdfuaid:rev`). It should be planned as a later phase, not as a flag on the UA-1 writer.
6. **Generators emit no-op operators** (empty `BT/ET`, unused font references). Content-stream normalization has to happen before tagging.
