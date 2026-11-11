#!/usr/bin/env python3
"""Logging-only edits to an ephemeral backend copy; require exact unique anchors."""
import pathlib, sys
p = pathlib.Path(sys.argv[1])
s = p.read_text()
a = '                dim3 g(bw, (unsigned)kz, (unsigned)((S + sr - 1) / sr));'
b = a + '\n                fprintf(stderr, "DISPATCH W4 I=%d O=%d S=%d ks=%d kc=%d kz=%d sr=%d shared=%zu grid=%u,%u,%u\\n", t->I,t->O,S,ks,kc,kz,sr,sr*xrow,g.x,g.y,g.z);'
assert s.count(a) == 1
s = s.replace(a,b)
a = '        while (nr > 1 && nr * prow > 48 * 1024) nr--;'
b = a + '\n        fprintf(stderr, "DISPATCH FALLBACK I=%d O=%d S=%d nr=%d shared=%zu grid=%u,%u,1\\n",t->I,t->O,S,nr,nr*prow,bx,(unsigned)((S+nr-1)/nr));'
assert s.count(a) == 1
s = s.replace(a,b)
p.write_text(s)
