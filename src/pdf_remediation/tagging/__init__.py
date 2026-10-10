"""Structure (tag) engines: the built-in engine and OpenDataLoader."""
from .basic import tag_document
from .odl import odl_autotag, odl_available, odl_installed

__all__ = ["tag_document", "odl_autotag", "odl_available", "odl_installed"]
