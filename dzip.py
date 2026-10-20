# -*- coding: utf-8 -*-
"""DZIP codec, reverse-engineered from dariusburstcs.exe.

File layout: 'DZIP' + u32 LE usize + stream (from offset 8).
Stream: first byte is copied literally as output[0]; then a bitstream
(MSB-first; flag bytes interleaved in the same stream) drives ops:
  0            literal: next stream byte
  10 + g1      if prev op was a literal and g1==2: repeat-match
                   n = g2 (getbits); copy n bytes from out_pos - rep_off
               else long match:
                   off = ((g1 - adj) << 8) + next stream byte,
                   adj = 2 if prev op was a match else 3
                   n  = g2 + bonus(off), bonus = (off>=0x7d00) + (off>=0x500)
                        + (2 if off<0x80 else 0)
  110 + byte   short match: off = byte>>1 (0 => END), len = (byte&1)+2
  111 + 4bits  v==0: output 0x00 ; else copy 1 byte from out_pos - v
getbits(): acc=1; loop { acc = acc*2 + bit; } while (bit());
           returns >= 2 (Elias-gamma-like, implicit leading 1).
Copy is byte-by-byte forward from the absolute position out_pos - off,
so overlapping (RLE-style) matches are legal.
"""
import struct


class _BitReader:
    __slots__ = ('stream', 'inp', 'bitbuf', 'bitcnt')

    def __init__(self, stream):
        self.stream = stream
        self.inp = 1          # stream[0] is consumed as output[0]
        self.bitbuf = 0
        self.bitcnt = 0

    def bit(self):
        if self.bitcnt == 0:
            self.bitbuf = self.stream[self.inp]
            self.inp += 1
            self.bitcnt = 8
        b = (self.bitbuf >> 7) & 1
        self.bitbuf = (self.bitbuf << 1) & 0xFF
        self.bitcnt -= 1
        return b

    def gamma(self):
        acc = 1
        while True:
            acc = acc * 2 + self.bit()
            if self.bit() == 0:
                return acc


def decompress(stream, usz=None):
    out = bytearray()
    out.append(stream[0])
    br = _BitReader(stream)
    rep_off = 0
    prev_match = False
    while True:
        if br.bit() == 0:                       # literal
            out.append(stream[br.inp])
            br.inp += 1
            prev_match = False
            continue
        if br.bit() == 0:                       # '10'
            g1 = br.gamma()
            if not prev_match and g1 == 2:      # repeat match
                n = br.gamma()
                if n == 0:
                    break
                for _ in range(n):
                    out.append(out[len(out) - rep_off])
                prev_match = True
            else:                               # long match
                off = ((g1 - (2 if prev_match else 3)) << 8) + stream[br.inp]
                br.inp += 1
                rep_off = off
                n = br.gamma() + (off >= 0x7d00) + (off >= 0x500) + (2 if off < 0x80 else 0)
                if n == 0:
                    break
                for _ in range(n):
                    out.append(out[len(out) - off])
                prev_match = True
            continue
        if br.bit() == 0:                       # '110' short match / end
            byte = stream[br.inp]
            br.inp += 1
            off = byte >> 1
            if off == 0:
                break                           # end marker
            rep_off = off
            for _ in range((byte & 1) + 2):
                out.append(out[len(out) - off])
            prev_match = True
            continue
        v = 0                                   # '111' single-byte match
        for _ in range(4):
            v = v * 2 + br.bit()
        # both single-match and zero-write fall into the shared tail
        # (inc out; xor ebx,ebx) => state becomes literal-like
        if v == 0:
            out.append(0)
        else:
            out.append(out[len(out) - v])
        prev_match = False
    if usz is not None and len(out) != usz:
        raise ValueError('size mismatch: got %d expected %d' % (len(out), usz))
    return bytes(out)


def parse_file(data):
    if data[:4] != b'DZIP':
        raise ValueError('bad magic %r' % data[:4])
    usz, = struct.unpack_from('<I', data, 4)
    return decompress(data[8:], usz), usz


# ----------------------------------------------------------------------------
# Encoder

def _gbits(v):
    """bits used by gamma coding of v (v >= 2)."""
    return 2 * (v.bit_length() - 1)


class _BitWriter:
    """Mirrors the decoder's interleaved bit/byte cursor exactly:
    a flag byte is inserted into the stream at the position where the
    decoder's cursor sits when it needs the first bit of that byte."""
    __slots__ = ('out', 'flag_pos', 'flag_cnt')

    def __init__(self, out):
        self.out = out
        self.flag_pos = -1
        self.flag_cnt = 0

    def bit(self, b):
        if self.flag_cnt == 0:
            self.flag_pos = len(self.out)
            self.out.append(0)
        if b:
            self.out[self.flag_pos] |= 1 << (7 - self.flag_cnt)
        self.flag_cnt += 1
        if self.flag_cnt == 8:
            self.flag_cnt = 0

    def byte(self, b):
        self.out.append(b)

    def gamma(self, v):
        assert v >= 2, v
        bits = bin(v)[3:]
        last = len(bits) - 1
        for i, b in enumerate(bits):
            self.bit(int(b))
            self.bit(0 if i == last else 1)


def _bonus(off):
    return (1 if off >= 0x7d00 else 0) + (1 if off >= 0x500 else 0) \
        + (2 if off < 0x80 else 0)


def encode(content):
    """Compress content into a DZIP stream (without the 12-byte file header)."""
    n = len(content)
    out = bytearray([content[0]])
    bw = _BitWriter(out)
    prev_match = False
    rep_off = 0
    # hash chains on 3-byte prefixes
    heads = {}
    MAXCHAIN = 48

    def find_match(i, state_match, rep):
        """returns op tuple best at i, one of
        ('lit',), ('zero',), ('single',off), ('short',off,ln),
        ('long',off,ln), ('rep',rep,ln)"""
        cands = [(9.001, 9, 1, ('lit',))]
        if content[i] == 0:
            cands.append((7.001, 7, 1, ('zero',)))
        if i >= 16:
            for off in range(1, 16):
                if content[i - off] == content[i]:
                    cands.append((7.001, 7, 1, ('single', off)))
                    break
        if i + 1 < n:
            for off in range(1, 128):
                j = i - off
                if j < 0:
                    break
                if content[j] == content[i] and content[j + 1] == content[i + 1]:
                    ln = 3 if (i + 2 < n and content[j + 2] == content[i + 2]) else 2
                    cands.append((11 / ln, 11, ln, ('short', off, ln)))
        adj = 2 if state_match else 3
        chain = heads.get(content[i:i + 3]) if i + 2 < n else None
        if chain:
            maxback = min(i, 1 << 18)
            best_long = None
            cnt = 0
            cap = min(n - i, 512)
            for j in reversed(chain):
                off = i - j
                if off > maxback:
                    break
                cnt += 1
                if cnt > 16:
                    break
                if best_long is not None:
                    bl = best_long[2]
                    if i + bl < n and content[j + bl] != content[i + bl]:
                        continue
                ln = 3
                while ln < cap and content[j + ln] == content[i + ln]:
                    ln += 1
                bon = _bonus(off)
                el = ln - bon
                if el < 2:
                    continue  # too short to encode as a long match at this offset
                g1 = (off >> 8) + adj
                cost = 2 + _gbits(g1) + 8 + _gbits(el)
                sc = cost / ln
                if best_long is None or sc < best_long[0]:
                    best_long = (sc, cost, ln, ('long', off, ln))
            if best_long:
                cands.append(best_long)
        if not state_match and 0 < rep <= i and i + 1 < n:
            j = i - rep
            if content[j] == content[i] and content[j + 1] == content[i + 1]:
                ln = 2
                cap = min(n - i, 512)
                while ln < cap and content[j + ln] == content[i + ln]:
                    ln += 1
                cost = 4 + _gbits(ln)
                cands.append((cost / ln, cost, ln, ('rep', rep, ln)))
        cands.sort(key=lambda t: (t[0], -t[2]))
        return cands[0][3]

    i = 1
    while i < n:
        op = find_match(i, prev_match, rep_off)
        kind = op[0]
        if kind == 'lit':
            bw.bit(0)
            bw.byte(content[i])
            ln = 1
            prev_match = False
        elif kind == 'zero':
            bw.bit(1); bw.bit(1); bw.bit(1)
            for _ in range(4):
                bw.bit(0)
            ln = 1
            prev_match = False
        elif kind == 'single':
            off = op[1]
            bw.bit(1); bw.bit(1); bw.bit(1)
            for sh in (3, 2, 1, 0):
                bw.bit((off >> sh) & 1)
            ln = 1
            prev_match = False
        elif kind == 'short':
            off, ln = op[1], op[2]
            bw.bit(1); bw.bit(1); bw.bit(0)
            bw.byte(off * 2 + (ln - 2))
            rep_off = off
            prev_match = True
        elif kind == 'long':
            off, ln = op[1], op[2]
            adj = 2 if prev_match else 3
            g1 = (off >> 8) + adj
            enc_len = ln - _bonus(off)
            bw.bit(1); bw.bit(0)
            bw.gamma(g1)
            bw.byte(off & 0xFF)
            bw.gamma(enc_len)
            rep_off = off
            prev_match = True
        else:  # rep
            rep, ln = op[1], op[2]
            bw.bit(1); bw.bit(0)
            bw.gamma(2)
            bw.gamma(ln)
            prev_match = True
        # advance hash chains over the consumed region (3-byte keys need i+3<=n)
        target = i + ln
        stop = min(target, n - 2)
        while i < stop:
            heads.setdefault(content[i:i + 3], []).append(i)
            i += 1
        i = target
    # end marker: '110' + byte with off==0
    bw.bit(1); bw.bit(1); bw.bit(0)
    bw.byte(0)
    return bytes(out)


def build_file(node_content, tag=b'\xc0\x2c\xb2\xb8', pad=2):
    """node_content = the decompressed payload starting with the 4-byte tag.
    Returns complete .dxt file bytes. Mirrors the original layout:
    node = tag + szA + szB + tsv + pad*0x00, usz = len(node)."""
    szB = len(node_content) - 12
    usz = len(node_content) + pad
    node = bytearray(node_content)
    node[4:8] = struct.pack('<I', usz - 8)
    node[8:12] = struct.pack('<I', szB)
    node += b'\x00' * pad
    assert len(node) == usz
    stream = encode(bytes(node))
    return b'DZIP' + struct.pack('<I', usz) + stream, usz


if __name__ == '__main__':
    import sys, os
    here = os.path.dirname(os.path.abspath(__file__))
    # test 1: localizationtext.dxt vs runtime oracle
    data = open(os.path.join(here, '..', 'jp', 'data', 'localizationtext', 'localizationtext.dxt'), 'rb').read()
    out, usz = parse_file(data)
    print('localizationtext: usz=%d decompressed=%d head=%r' % (usz, len(out), out[:24]))
    oracle = open(os.path.join(here, 'dumps', 'oracle_c02cb2b8_11d99760.bin'), 'rb').read()
    print('oracle len=%d  match_full=%s match_after4=%s' % (
        len(oracle), out == oracle, out[4:] == oracle[4:] if len(oracle) == len(out) else 'n/a'))
    # test 2: errormsg font payload (find its dxt)
    for root, dirs, files in os.walk(os.path.join(here, '..', 'jp')):
        for f in files:
            if 'errormsg' in f.lower() and f.lower().endswith('.dxt'):
                p = os.path.join(root, f)
                d2 = open(p, 'rb').read()
                o2, u2 = parse_file(d2)
                ref = open(os.path.join(here, 'dumps', 'errormsg_payload.bin'), 'rb').read()
                print('%s: usz=%d dec=%d ref=%d equal=%s equal4=%s' % (
                    p, u2, len(o2), len(ref), o2 == ref,
                    o2[4:] == ref[4:] if len(ref) == len(o2) else 'n/a'))
