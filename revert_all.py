# -*- coding: utf-8 -*-
"""FULL REVERT: restore every modified game file from its .bak original.

Run:  python revert_all.py          (restores everything)
      python revert_all.py --list   (shows what would be restored, no changes)

Covers: all jp/data/test/*.dxt + jp/images/*_0.tx2 with a .bak,
localizationtext.dxt, orcanewmode_telopstrs.dxt.
The ch/ language directory is official Steam content and is never touched.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.path.join(HERE, '..'))
JP = os.path.join(GAME, 'jp')

def collect():
    jobs = []
    tdir = os.path.join(JP, 'data', 'test')
    for f in sorted(os.listdir(tdir)):
        if f.endswith('.dxt.bak'):
            name = f[:-8]
            jobs.append((os.path.join(tdir, f), os.path.join(tdir, name + '.dxt')))
            txb = os.path.join(JP, 'images', name + '_0.tx2.bak')
            if os.path.exists(txb):
                jobs.append((txb, os.path.join(JP, 'images', name + '_0.tx2')))
    for rel in ['data/localizationtext/localizationtext.dxt',
                'data/orcanewmode/orcanewmode_telopstrs.dxt']:
        p = os.path.join(JP, rel)
        if os.path.exists(p + '.bak'):
            jobs.append((p + '.bak', p))
    return jobs

def main():
    jobs = collect()
    for src, dst in jobs:
        print('%s  ->  %s' % (os.path.relpath(src, GAME), os.path.relpath(dst, GAME)))
    if '--list' in sys.argv:
        print('(dry run, nothing changed)')
        return
    for src, dst in jobs:
        shutil.copy2(src, dst)
    print('restored %d files to originals' % len(jobs))

if __name__ == '__main__':
    main()
