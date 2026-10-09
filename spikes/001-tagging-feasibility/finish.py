"""Document-level 'finisher' applied after auto-tagging: the steps ODL leaves to its paid add-on."""
import sys, pikepdf
from pikepdf import Dictionary, Name, String
p = pikepdf.open(sys.argv[1]); r = p.Root
title = sys.argv[3]
r.MarkInfo = Dictionary(Marked=True)
r.Lang = String("en-US")
r.ViewerPreferences = Dictionary(DisplayDocTitle=True)
for pg in p.pages: pg.obj.Tabs = Name.S
with p.open_metadata(set_pikepdf_as_editor=False) as m:
    m["dc:title"] = title
    m.register_xml_namespace("http://www.aiim.org/pdfua/ns/id/", "pdfuaid")
    m["pdfuaid:part"] = "1"
p.docinfo["/Title"] = title
p.save(sys.argv[2])
