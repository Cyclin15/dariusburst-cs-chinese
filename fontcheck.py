import os, sys, struct
import dzip

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, '..'))

def parse_bmf(b):
    assert b[:4] == b'BMF\x03', b[:4]
    i = 4
    info = common = pages = None
    chars = {}
    kern = []
    while i < len(b):
        if i + 5 > len(b):
            break  # trailing pad
        bid = b[i]; size, = struct.unpack_from('<I', b, i+1)
        data = b[i+5:i+5+size]
        if bid == 1: info = data
        elif bid == 2: common = data
        elif bid == 3: pages = data
        elif bid == 4:
            for k in range(0, size, 20):
                cid, = struct.unpack_from('<I', data, k)
                chars[cid] = struct.unpack_from('<HHHhhhHBB', data, k+4)
        elif bid == 5:
            for k in range(0, size - 9, 10):
                kern.append(struct.unpack_from('<IIh', data, k))
        else: print('unknown block', bid, size)
        i += 5 + size
    return info, common, pages, chars, kern

def load(lang, name):
    p = os.path.join(GAME, lang, 'data', 'test', name)
    if not os.path.exists(p): return None
    node, usz = dzip.parse_file(open(p, 'rb').read())
    szB, = struct.unpack_from('<I', node, 8)
    return node[12:12+szB]

def main():
    # collect every char used in translations (ch column output)
    from translations import TRANSLATIONS
    used = set()
    for v in TRANSLATIONS.values():
        used.update(v)
    used.discard('@')  # newline marker, not rendered
    used.discard('\\')  # escapes
    used = {c for c in used if c not in '\r'}

    names = sorted(f for f in os.listdir(os.path.join(GAME, 'ch', 'data', 'test')) if f.endswith('.dxt'))
    print('%-44s %6s %6s  missing' % ('font', 'glyphs', 'miss'))
    allmiss = {}
    for name in names:
        b = load('ch', name)
        if b is None or not b.startswith(b'BMF'): 
            print('%-44s (not BMF)' % name); continue
        info, common, pages, chars, kern = parse_bmf(b)
        miss = sorted(c for c in used if ord(c) not in chars)
        print('%-44s %6d %6d  %s' % (name, len(chars), len(miss), ''.join(miss[:40])))
        allmiss[name] = miss

    # summary: chars missing from EVERY font
    common_miss = set(used)
    for name, miss in allmiss.items():
        if miss is not None and miss != []:
            pass
    sets = [set(m) for m in allmiss.values() if m is not None]
    if sets:
        inter = set.intersection(*sets) if sets else set()
        uni = set.union(*sets)
        print()
        print('total used chars:', len(used))
        print('missing from ALL fonts (%d): %s' % (len(inter), ''.join(sorted(inter))))
        print('missing from SOME font, present in >=1 font (%d): %s' % (len(uni - inter), ''.join(sorted(uni - inter))))

if __name__ == '__main__':
    main()
