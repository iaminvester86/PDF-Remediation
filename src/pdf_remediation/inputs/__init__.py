"""Where work comes from: local files, folders, zip archives and links."""
from .files import InputError, InputFile, collect_paths, extract_zip, inspect_pdf, looks_like_pdf, safe_relpath
from .links import FetchResult, fetch_inputs

__all__ = ["FetchResult", "InputError", "InputFile", "collect_paths", "extract_zip", "fetch_inputs", "inspect_pdf",
           "looks_like_pdf", "safe_relpath"]
