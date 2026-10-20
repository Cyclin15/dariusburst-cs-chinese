# -*- coding: utf-8 -*-
"""Insert a telop_ch column into orcanewmode_telopstrs.dxt (CS mode story).
Column order becomes: telopId, telop_jp, telop_en, telop_ch, telop_fr, ...
matching the exe's language table (jp,en,ch,fr,it,ge,sp,po,ru)."""
import os, sys, struct, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dzip
from telop_zh import TELOP_ZH

HERE = os.path.dirname(os.path.abspath(__file__))
DXT = os.path.abspath(os.path.join(HERE, '..', 'jp', 'data', 'orcanewmode', 'orcanewmode_telopstrs.dxt'))
BAK = DXT + '.bak'
SRC = BAK if os.path.exists(BAK) else DXT

def main():
    data = open(SRC, 'rb').read()
    node, usz = dzip.parse_file(data)
    tag = node[:4]
    szA, szB = struct.unpack_from('<II', node, 4)
    txt = node[12:12 + szB].decode('utf-8')
    assert node[12 + szB:] == b'', 'unexpected trailing bytes: %r' % node[12 + szB:][:16]
    lines = txt.split('\r\n')
    print('lines: %d, first=%r..., last=%r' % (len(lines), lines[0][:30], lines[-1][:40]))
    rows = [l.split('\t') for l in lines]
    # header
    assert rows[0][1:3] == ['telop_jp', 'telop_en'], rows[0][:4]
    ncol = len(rows[0])
    assert all(len(r) == ncol for r in rows), set(len(r) for r in rows)

    new_rows = [[rows[0][0], 'telop_jp', 'telop_en', 'telop_ch'] + rows[0][3:]]
    n_trans = n_nodata = n_empty = 0
    for r in rows[1:]:
        rid = r[0]
        if rid in TELOP_ZH:
            v = TELOP_ZH[rid]
            assert '\t' not in v and '\n' not in v and '\r' not in v
            n_trans += 1
        elif r[2] == '' and any(c.startswith('no_data') for c in r[1:]):
            v = 'no_data_ch'
            n_nodata += 1
        elif r[2] == '':
            v = ''
            n_empty += 1
        else:
            raise AssertionError('untranslated telop row: %s en=%r' % (rid, r[2][:60]))
        new_rows.append([r[0], r[1], r[2], v] + r[3:])
    print('translated=%d no_data=%d empty=%d (of %d data rows)' % (
        n_trans, n_nodata, n_empty, len(rows) - 1))
    assert n_trans + n_nodata + n_empty == len(rows) - 1

    new_txt = '\r\n'.join('\t'.join(r) for r in new_rows)
    assert new_txt.split('\r\n') == ['\t'.join(r) for r in new_rows]
    payload = new_txt.encode('utf-8')
    new_node = tag + struct.pack('<II', 12 + len(payload) - 8, len(payload)) + payload
    assert len(new_node) == 12 + len(payload)
    newfile = b'DZIP' + struct.pack('<I', len(new_node)) + dzip.encode(new_node)

    if not os.path.exists(BAK):
        shutil.copy2(DXT, BAK)
        print('backup written')
    open(DXT, 'wb').write(newfile)
    print('replaced: %s (%d bytes, orig %d)' % (DXT, len(newfile), len(data)))

    # verify from disk
    chk, chusz = dzip.parse_file(open(DXT, 'rb').read())
    cszB, = struct.unpack_from('<I', chk, 8)
    assert chk[12 + cszB:] == b''
    t = chk[12:12 + cszB].decode('utf-8')
    cl = t.split('\r\n')
    assert cl[0].split('\t')[3] == 'telop_ch'
    assert len(cl) == len(lines)
    for old, new in zip(rows, [l.split('\t') for l in cl]):
        assert old[0] == new[0] and old[1] == new[1] and old[2] == new[2] and old[3:] == new[4:]
    # spot check the user-quoted row
    for l in cl:
        c = l.split('\t')
        if c[0] == 'telop_st2_1_002_01':
            print('spot check st2_1_002_01 ch:', c[3])
    print('verify-from-disk OK')

if __name__ == '__main__':
    main()
