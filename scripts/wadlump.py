# Prints one lump of a WAD to stdout:   python3 -I scripts/wadlump.py WAD NAME > OUT
import struct, sys
d = open(sys.argv[1], 'rb').read()
n, off = struct.unpack('<4xii', d[:12])
for i in range(n):
    p, l, name = struct.unpack('<ii8s', d[off + 16 * i: off + 16 * i + 16])
    if name.rstrip(b'\0').decode() == sys.argv[2]:
        sys.stdout.buffer.write(d[p:p + l]); break
else:
    sys.exit('no lump ' + sys.argv[2])
