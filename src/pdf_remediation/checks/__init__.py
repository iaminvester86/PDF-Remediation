"""Checks: veraPDF validation, semantic QA, and the rendering/text safety gates."""
from .gates import text_diff, visual_diff
from .semantic import ALT_PLACEHOLDER_RE, QAResult, alt_needs_work, run_qa
from .verapdf import run_verapdf, verapdf_issues

__all__ = ["ALT_PLACEHOLDER_RE", "QAResult", "alt_needs_work", "run_qa", "run_verapdf", "text_diff",
           "verapdf_issues", "visual_diff"]
