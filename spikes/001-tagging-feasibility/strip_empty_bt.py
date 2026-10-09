"""Remove BT..ET blocks that show no text (they still reference fonts, e.g. non-embedded Helvetica)."""
import sys, pikepdf
SHOW = {"Tj", "TJ", "'", '"'}
p = pikepdf.open(sys.argv[1]); removed = 0
for pg in p.pages:
    ops = pikepdf.parse_content_stream(pg); out, buf = [], None
    for operands, op in ops:
        n = str(op)
        if n == "BT": buf = [(operands, op)]; continue
        if buf is not None:
            buf.append((operands, op))
            if n == "ET":
                if any(str(o) in SHOW for _, o in buf): out.extend(buf)
                else: removed += 1
                buf = None
            continue
        out.append((operands, op))
    pg.obj.Contents = p.make_stream(pikepdf.unparse_content_stream(out))
p.save(sys.argv[2]); print("removed empty text blocks:", removed)
