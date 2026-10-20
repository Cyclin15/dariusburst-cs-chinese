# -*- coding: utf-8 -*-
"""Regenerate game UI fonts with full Chinese glyph coverage at each
font's ORIGINAL pixel size, using Windows simhei.ttf.

For each target font:
  - read the ORIGINAL .dxt (prefer .bak) -> clone info/common/pages blocks,
    keep original lineHeight/base/fontSize
  - render charset (ch-column chars + ASCII + original charset) with PIL,
    anchor='ls' (pen/baseline) + ink-crop for exact xoff/yoff
  - shelf-pack into an atlas whose dims match an existing donor texture
  - emit new BMF .dxt (tag c02cb2b8, no pad) and .tx2 (tag 8460f222,
    node B-field + tex-header random prefix from the original file,
    [0101 0003 + rest24] from a same-dims donor,
    white RGB + alpha coverage pixels, top-down)
"""
import os, sys, struct, shutil
import dzip
from fontcheck import parse_bmf
from translations import TRANSLATIONS
from PIL import Image, ImageFont, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, '..'))
JP = os.path.join(GAME, 'jp')
TTF = r'C:\Windows\Fonts\simhei.ttf'

TAG_DXT = bytes.fromhex('c02cb2b8')
TAG_TX2 = bytes.fromhex('8460f222')

# fonts to regenerate (all render potentially-localized text)
TARGETS = [
    'font_system_9', 'font_system_14', 'font_system_18', 'font_system_24',
    'font_system_32', 'font_system_36', 'font_system_48', 'font_system_60',
    'font_rodin_pro40', 'font_rodin_pro_ahk42',
    'font_rodin_pro_b_32', 'font_rodin_pro_b_48', 'font_rodin_pro_b_54',
    'font_rodin_pro_b_60',
    'font_rodin_ntlgpro50', 'font_rodin_ntlgpro60', 'font_rodin_ntlgprodb40',
    'font_rodin_ntlgprob36_chrstats',
    'font_rodin_prob100_calloperator', 'font_rodin_prob100_chrores',
    'font_rodin_prob22_player', 'font_rodin_prob32_errormsg',
    'font_rodin_prob80_error', 'font_rodin_prol20_player',
    'telop_font', 'font_msgothic_32_alpha',
]

def orig_path(dirpath, name, ext):
    p = os.path.join(dirpath, name + ext)
    if os.path.exists(p + '.bak'):
        return p + '.bak'
    return p

def load_node(path):
    data = open(path, 'rb').read()
    node, usz = dzip.parse_file(data)
    return node, usz

def ch_column_chars():
    node, _ = load_node(os.path.join(JP, 'data', 'localizationtext', 'localizationtext.dxt.bak'))
    szB, = struct.unpack_from('<I', node, 8)
    tsv = node[12:12 + szB].decode('utf-8')
    rows = [l.split('\t') for l in tsv.split('\n')[:-1]]
    chars = set()
    for r in rows:
        rid = int(r[0].lstrip('\ufeff'))
        txt = TRANSLATIONS.get(rid, r[3])
        chars.update(txt)
    chars = {c for c in chars if c not in '@\r\n'}
    # CS mode story telop texts (orcanewmode_telopstrs telop_ch column)
    from telop_zh import TELOP_ZH
    for v in TELOP_ZH.values():
        chars.update(v)
    chars = {c for c in chars if c not in '@\r\n'}
    chars |= set(chr(c) for c in range(0x20, 0x7F))
    return chars

def collect_donors():
    """(w,h) -> 40-byte texture header, from every ORIGINAL tx2.
    .bak (original) is preferred over the live file, which may be one of
    our regenerated fonts (whose synthesized headers must not leak back
    in as 'donors')."""
    donors = {}
    idir = os.path.join(JP, 'images')
    bases = sorted(f[:-4] for f in os.listdir(idir) if f.endswith('.tx2'))
    for base in bases:
        p = os.path.join(idir, base + '.tx2.bak')
        if not os.path.exists(p):
            p = os.path.join(idir, base + '.tx2')   # never modified: original
        try:
            node, _ = load_node(p)
            inner = node[12:]
            u16 = struct.unpack_from('<12H', inner, 16)
            w, h = u16[1], u16[3]
            assert inner[12:16] == b'\x01\x01\x00\x03'
            donors.setdefault((w, h), inner[:40])
        except Exception:
            pass
    return donors

def render_glyphs(size, charset, cjk_size=None):
    """char -> (L image|None, xoff, yoff_from_baseline, xadvance).
    xoff/yoff measured exactly by drawing at anchor 'ls' (pen, baseline)
    and cropping the ink box.  cjk_size: render CJK chars at a reduced
    pixel size (same baseline) so the atlas fits a real donor texture."""
    font = ImageFont.truetype(TTF, size)
    cfont = ImageFont.truetype(TTF, cjk_size) if cjk_size else font
    S = size + 16
    out = {}
    for ch in charset:
        f = cfont if cjk_size and ord(ch) > 0x2E7F else font
        adv = int(round(f.getlength(ch)))
        if adv <= 0:
            adv = max(size // 2, 1)
        cv = Image.new('L', (S * 4, S * 4), 0)
        ImageDraw.Draw(cv).text((S, S), ch, 255, font=f, anchor='ls')
        ib = cv.getbbox()
        if ib is None:
            out[ch] = (None, 0, 0, adv)
        else:
            out[ch] = (cv.crop(ib), ib[0] - S, ib[1] - S, adv)
    return out

def pack(glyphs, dims_candidates):
    """shelf-pack ink boxes; returns ((W,H), {ch:(x,y)}) or None."""
    items = [(ch, g[0]) for ch, g in glyphs.items() if g[0] is not None]
    items.sort(key=lambda t: (-t[1].height, -t[1].width, t[0]))
    for W, H in dims_candidates:
        x, y, rowh = 1, 1, 0
        pos = {}
        ok = True
        for ch, img in items:
            w, h = img.width, img.height
            if x + w + 1 > W:
                x = 1
                y += rowh + 1
                rowh = 0
            if y + h + 1 > H:
                ok = False
                break
            pos[ch] = (x, y)
            x += w + 1
            rowh = max(rowh, h)
        if ok:
            return (W, H), pos
    return None

def tex_header(W, H, pre12):
    """40-byte tx2 texture header: 12 per-file bytes + fixed fmt +
    dims-derived rest24 (formula verified against all 35 original dims)."""
    V = W * H * 4
    w2 = (W + 7) & ~7
    rest24 = struct.pack('<12H', 0, W, W, H, V & 0xFFFF, V >> 16,
                         w2, w2, H, 0, V & 0xFFFF, V >> 16)
    return pre12 + b'\x01\x01\x00\x03' + rest24

def build_bmf(orig_bmf, glyphs, base, W, H, pos):
    info, common, pages, chars, kern = parse_bmf(orig_bmf)
    new_common = bytearray(common)
    struct.pack_into('<HH', new_common, 4, W, H)   # scaleW, scaleH
    recs = bytearray()
    for ch in sorted(glyphs):
        img, xoff, yoff_raw, adv = glyphs[ch]
        if img is None or ch not in pos:
            recs += struct.pack('<IHHHHhhhBB', ord(ch), 0, 0, 0, 0, 0, 0, adv, 0, 15)
        else:
            x, y = pos[ch]
            recs += struct.pack('<IHHHHhhhBB', ord(ch), x, y, img.width, img.height,
                                xoff, base + yoff_raw, adv, 0, 15)
    out = bytearray(b'BMF\x03')
    out += bytes([1]) + struct.pack('<I', len(info)) + info
    out += bytes([2]) + struct.pack('<I', len(new_common)) + bytes(new_common)
    out += bytes([3]) + struct.pack('<I', len(pages)) + pages
    out += bytes([4]) + struct.pack('<I', len(recs)) + bytes(recs)
    return bytes(out)

def build_tx2_bytes(orig_tx2_node, donor_header40, atlas_rgba):
    # keep original per-file random prefix (inner[0:12]) and node B-field
    texhdr = orig_tx2_node[12:24] + donor_header40[12:]
    inner = texhdr + atlas_rgba
    szA = len(inner) + 4
    bfield, = struct.unpack_from('<I', orig_tx2_node, 8)
    node = TAG_TX2 + struct.pack('<II', szA, bfield) + inner
    return b'DZIP' + struct.pack('<I', len(node)) + dzip.encode(node)

def build_dxt_bytes(bmf):
    node = TAG_DXT + struct.pack('<II', len(bmf) + 4, len(bmf)) + bmf
    return b'DZIP' + struct.pack('<I', len(node)) + dzip.encode(node)

def gen_font(name, ch_chars, donors, verbose=True, drop_orig_cjk=False):
    dxt = orig_path(os.path.join(JP, 'data', 'test'), name, '.dxt')
    tx2 = orig_path(os.path.join(JP, 'images'), name, '_0.tx2')
    if not (os.path.exists(dxt) and os.path.exists(tx2)):
        print('SKIP (missing files):', name)
        return None
    dnode, _ = load_node(dxt)
    dszB, = struct.unpack_from('<I', dnode, 8)
    orig_bmf = dnode[12:12 + dszB]
    info, common, pages, orig_chars, kern = parse_bmf(orig_bmf)
    size, = struct.unpack_from('<H', info, 0)
    lineHeight, base, sw, sh, npg = struct.unpack_from('<HHHHH', common, 0)

    orig_set = set(chr(c) for c in orig_chars if c >= 0x20)
    if drop_orig_cjk:
        orig_set = {c for c in orig_set
                    if not (0x3400 <= ord(c) <= 0x4DBF or 0x4E00 <= ord(c) <= 0x9FFF)}
    charset = set(ch_chars) | orig_set
    dims = sorted(donors.keys(), key=lambda d: d[0] * d[1])   # real dims only
    res = None
    cjk_size = None
    # try full-size first, then progressively smaller CJK until it fits a
    # real donor dim (original latin/kana glyphs always stay at full size)
    for cs in [None] + [s for s in range(size - 4, 47, -4) if s > 40]:
        glyphs = render_glyphs(size, charset, cjk_size=cs)
        res = pack(glyphs, dims)
        if res is not None:
            cjk_size = cs
            break
    if res is None:
        # too big with original charset union: keep only ch + ascii
        glyphs = render_glyphs(size, ch_chars)
        res = pack(glyphs, dims)
    if res is None:
        print('FAIL (no atlas dims fit):', name)
        return None
    (W, H), pos = res

    bmf = build_bmf(orig_bmf, glyphs, base, W, H, pos)

    atlas = Image.new('RGBA', (W, H), (255, 255, 255, 0))
    for ch, (img, xoff, yoff_raw, adv) in glyphs.items():
        if img is None or ch not in pos:
            continue
        rgba = Image.merge('RGBA', (Image.new('L', img.size, 255),
                                    Image.new('L', img.size, 255),
                                    Image.new('L', img.size, 255), img))
        atlas.paste(rgba, pos[ch])
    tnode, _ = load_node(tx2)
    header40 = donors.get((W, H)) or tex_header(W, H, tnode[12:24])
    tx2_bytes = build_tx2_bytes(tnode, header40, atlas.tobytes())
    dxt_bytes = build_dxt_bytes(bmf)
    blanks = [ch for ch, g in sorted(glyphs.items()) if g[0] is None]
    if verbose:
        print('%-42s size=%3d cjk=%s glyphs=%4d(blank %d %r) atlas=%dx%d (orig %dx%d, %d glyphs)' % (
            name, size, cjk_size, len(glyphs), len(blanks), ''.join(blanks[:10]), W, H, sw, sh, len(orig_chars)))
    return dxt_bytes, tx2_bytes, dxt, tx2

def install(name, built):
    dxt_bytes, tx2_bytes, orig_dxt, orig_tx2 = built
    dxt = os.path.join(JP, 'data', 'test', name + '.dxt')
    tx2 = os.path.join(JP, 'images', name + '_0.tx2')
    for orig, live in ((orig_dxt, dxt), (orig_tx2, tx2)):
        if not os.path.exists(live + '.bak'):
            shutil.copy2(live, live + '.bak')
    open(dxt, 'wb').write(dxt_bytes)
    open(tx2, 'wb').write(tx2_bytes)

CH_CHARS = None

def verify(name):
    dxt = os.path.join(JP, 'data', 'test', name + '.dxt')
    tx2 = os.path.join(JP, 'images', name + '_0.tx2')
    dnode, _ = load_node(dxt)
    dszB, = struct.unpack_from('<I', dnode, 8)
    bmf = dnode[12:12 + dszB]
    assert bmf[:4] == b'BMF\x03'
    info, common, pages, chars, kern = parse_bmf(bmf)
    tnode, _ = load_node(tx2)
    inner = tnode[12:]
    u16 = struct.unpack_from('<12H', inner, 16)
    W, H = u16[1], u16[3]
    lh, base, sw, sh, npg = struct.unpack_from('<HHHHH', common, 0)
    assert (sw, sh) == (W, H), (sw, sh, W, H)
    assert len(inner) == 40 + W * H * 4
    missing = [c for c in CH_CHARS if ord(c) not in chars]
    return len(chars), missing

def main():
    global CH_CHARS
    mode = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else 'all'
    CH_CHARS = ch_column_chars()
    print('charset (ch column + ascii): %d chars' % len(CH_CHARS))
    donors = collect_donors()
    print('donor dims:', sorted(donors.keys(), key=lambda d: d[0] * d[1]))
    names = TARGETS if mode == 'all' else [mode]
    for name in names:
        built = gen_font(name, CH_CHARS, donors)
        if not built:
            continue
        if '--dry' in sys.argv:
            continue
        install(name, built)
        n, missing = verify(name)
        status = 'OK' if not missing else 'MISSING:%s' % ''.join(missing[:20])
        print('   installed+verified: %d glyphs, coverage %s' % (n, status))

if __name__ == '__main__':
    main()
