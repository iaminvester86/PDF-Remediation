import sys, pikepdf
p = pikepdf.open(sys.argv[1]); r = p.Root
print("MarkInfo", r.get("/MarkInfo"), "Lang", r.get("/Lang"), "Title", p.docinfo.get("/Title"), "DisplayDocTitle", r.get("/ViewerPreferences", {}).get("/DisplayDocTitle") if "/ViewerPreferences" in r else None)
def text_of(k): return ""
def walk(e, d=0, budget=[70]):
    if budget[0] <= 0: return
    if isinstance(e, pikepdf.Dictionary) and e.get("/S") is not None:
        budget[0] -= 1
        extra = " Alt=%r" % str(e.Alt) if "/Alt" in e else ""
        extra += " A=%s" % e.A if "/A" in e else ""
        print("  " * d + str(e.S) + extra)
        k = e.get("/K")
        kids = k if isinstance(k, pikepdf.Array) else [k] if k is not None else []
        for c in kids: walk(c, d + 1)
st = r.get("/StructTreeRoot")
print("RoleMap", st.get("/RoleMap"))
walk(st.K if not isinstance(st.K, pikepdf.Array) else st.K[0])
