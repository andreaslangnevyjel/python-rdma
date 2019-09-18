#!/usr/bin/env python
# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.

import re
import sys

MATCH_NORMAL = r"([^.]+):\.+(.*)$"
MATCH_SA = r"\W+([^.]+)\.+(.*)$"


def matchify(ref, l_me, match):
    gr = [_f for _f in [re.match(match, obj) for obj in ref] if _f]
    gm = [_f for _f in [re.match(match, obj) for obj in l_me] if _f]
    gr = [(obj.groups()[0], obj.groups()[1]) for obj in gr]
    gm = [(obj.groups()[0], obj.groups()[1]) for obj in gm]

    idxm = 0
    idxr = 0
    while idxm < len(gm) and idxr < len(gr):
        r, ra = gr[idxr]
        m, ma = gm[idxm]
        if r != m:
            try:
                idxr = gr.index(m, idxr)
                continue
            except ValueError:
                pass

            try:
                idxm = gm.index(r, idxm)
                continue
            except ValueError:
                pass

            translate[m] = r
        else:
            if ra != ma:
                print(r, ra, ma)
        idxr = idxr + 1
        idxm = idxm + 1


def pull_file(file_obj):
    res = {}
    coll = []
    thing = None
    for line in file_obj.readlines():
        if line.startswith("------------- "):
            if coll:
                res[thing] = coll
            thing = line
            coll = []
        else:
            coll.append(line)
    return res


with open(sys.argv[1]) as f_obj:
    reference = pull_file(f_obj)
with open(sys.argv[2]) as f_obj:
    me = pull_file(f_obj)

translate = {}
for _thing, _coll in me.items():
    if _thing.find("saquery', 'NR") != -1:
        try:
            matchify(reference[_thing], _coll, MATCH_SA)
        except KeyError:
            pass
for I in translate.items():
    print("    %r: %r," % I)
