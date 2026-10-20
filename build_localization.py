# -*- coding: utf-8 -*-
"""Apply Chinese translations to the ch column of localizationtext,
repack as DZIP, verify round trip, backup and replace the game file."""
import os, sys, re, shutil, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dzip
from translations import TRANSLATIONS, KEEP

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, '..'))
DXT = os.path.join(GAME, 'jp', 'data', 'localizationtext', 'localizationtext.dxt')
BAK = DXT + '.bak'
SRC = BAK if os.path.exists(BAK) else DXT   # always build from the pristine original

def placeholders(s):
    return set(re.findall(r'%[1-5]', s))

def main():
    data = open(SRC, 'rb').read()
    node, usz = dzip.parse_file(data)
    tag = node[0:4]
    szA, szB = struct.unpack_from('<II', node, 4)
    tsv = node[12:12 + szB].decode('utf-8')
    lines = tsv.split('\n')
    assert lines[-1] == '', 'no trailing newline'
    rows = [l.split('\t') for l in lines[:-1]]
    assert all(len(r) == 10 for r in rows)

    # which rows were flagged (no_data_* / ascii-only / wrong-language)
    def has_cjk(s):
        return any('\u4e00' <= c <= '\u9fff' for c in s)
    flagged = []
    for r in rows:
        ch = r[3]
        if ch.startswith('no_data') or ch == 'no data' or ch == 'undefined' or \
           (ch and not has_cjk(ch)):
            flagged.append(int(r[0].lstrip('﻿')))
    flagged_set = set(flagged)
    ch_by_id = {int(r[0].lstrip('﻿')): r[3] for r in rows}
    trans_set = set(TRANSLATIONS)
    # rows whose official ch column is a literal 'undefined': fall back to
    # the English text (user is fine with English) unless we translate it.
    # Rows whose English is ALSO 'undefined' (e.g. arcade ad texts) keep the
    # original marker -- nothing better to show.
    en_fallback = set()
    for r in rows:
        rid = int(r[0].lstrip('﻿'))
        if r[3] == 'undefined' and rid not in TRANSLATIONS:
            if r[2] and r[2] != 'undefined':
                r[3] = r[2]
                en_fallback.add(rid)
    keep_dyn = KEEP | ({int(r[0].lstrip('﻿')) for r in rows
                        if r[3] == 'undefined'} - en_fallback)
    missing = flagged_set - trans_set - keep_dyn - en_fallback
    extra = trans_set - flagged_set
    # rows whose original ch column already has CJK (official just left
    # Japanese text there, e.g. the boss warning telops) may be retranslated
    extra = {rid for rid in extra if not has_cjk(ch_by_id[rid])}
    assert not missing, 'flagged but not translated/kept: %s' % sorted(missing)
    assert not extra, 'translated but not flagged: %s' % sorted(extra)

    # apply translations; then glyph-convert EVERY row's ch column (the
    # original official ch text is simplified too and the font has no
    # simplified glyphs)
    changed = 0
    for r in rows:
        rid = int(r[0].lstrip('\ufeff'))
        if rid in TRANSLATIONS:
            new = TRANSLATIONS[rid]
            # placeholder sanity: %N used must exist in ja/en of this row
            allowed = placeholders(r[1]) | placeholders(r[2])
            used = placeholders(new)
            assert used <= allowed, 'row %d uses %s not in %s' % (rid, used, allowed)
            assert '\t' not in new and '\n' not in new
            changed += 1
        else:
            new = r[3]
        r[3] = new
    print('rows flagged: %d, translated: %d, kept: %d' % (
        len(flagged), changed, len(flagged_set & KEEP)))

    # font coverage: every char in translated col3 must exist in the main
    # ch font (font_rodin_ntlgpro24) or be plain ASCII
    from fontcheck import parse_bmf, load as font_load
    _b = font_load('ch', 'font_rodin_ntlgpro24.dxt')
    _info, _common, _pages, font_chars, _kern = parse_bmf(_b)
    bad = []
    for r in rows:
        for c in r[3]:
            if c in '@\r\n' or c.isascii():
                continue
            if ord(c) not in font_chars:
                bad.append((r[0], c))
    assert not bad, 'chars missing from main font: %s' % bad[:30]
    print('font coverage OK: all col3 chars present in font_rodin_ntlgpro24 (%d glyphs)' % len(font_chars))

    new_tsv = '\n'.join('\t'.join(r) for r in rows) + '\n'
    assert new_tsv.split('\n')[:-1] == ['\t'.join(r) for r in rows]
    # only col 3 changed
    old_rows = tsv.split('\n')[:-1]
    new_rows = new_tsv.split('\n')[:-1]
    assert len(old_rows) == len(new_rows)
    for a, b in zip(old_rows, new_rows):
        ca, cb = a.split('\t'), b.split('\t')
        assert ca[0] == cb[0] and ca[1] == cb[1] and ca[2] == cb[2] and ca[4:] == cb[4:], \
            'non-col3 change in row %s' % ca[0]

    new_node = tag + struct.pack('<II', 0, len(new_tsv.encode('utf-8'))) + \
        new_tsv.encode('utf-8')
    newfile, new_usz = dzip.build_file(new_node)
    # full round-trip verification (build_file appends the 2-byte pad)
    expected = new_node[:4] + struct.pack('<II', new_usz - 8, len(new_tsv.encode('utf-8'))) \
        + new_tsv.encode('utf-8') + b'\x00\x00'
    rt_node, rt_usz = dzip.parse_file(newfile)
    assert rt_node == expected, 'round-trip mismatch'
    rt_tsv = rt_node[12:12 + struct.unpack_from("<I", rt_node, 8)[0]].decode('utf-8')
    assert rt_tsv == new_tsv
    print('new dxt: %d bytes (orig %d), usz=%d, round-trip OK' % (
        len(newfile), len(data), new_usz))

    if not os.path.exists(BAK):
        shutil.copy2(DXT, BAK)
        print('backup written:', BAK)
    open(DXT, 'wb').write(newfile)
    print('replaced:', DXT)
    # final independent check from disk
    chk, _ = dzip.parse_file(open(DXT, 'rb').read())
    assert chk == expected
    t = chk[12:12 + struct.unpack_from("<I", chk, 8)[0]].decode('utf-8')
    n_nodata = sum(1 for l in t.split('\n') if 'no_data_ch' in l.split('\t')[3:4])
    print('verify-from-disk OK; rows with no_data_ch in col3:', n_nodata)

if __name__ == '__main__':
    main()
