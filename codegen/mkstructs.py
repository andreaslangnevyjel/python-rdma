#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.
# ./mkstructs.py -x iba_transport.xml -x iba_12.xml -x iba_13_4.xml -x iba_13_6.xml -x iba_14.xml -x iba_15.xml
# -x iba_16_1.xml -x iba_16_3.xml -x iba_16_4.xml -x iba_16_5.xml  -o ../rdma/IBA_struct.py -r ../doc/iba_struct.inc

"""This script converts the XML descriptions of IB structures into python
   classes and associated codegen"""

import optparse
import os
import re
from contextlib import contextmanager
from functools import reduce
from xml.etree import ElementTree

# From IBA.py - including this by name creates a circular module dependency
# that is easier to break this way.
MAD_METHOD_GET = 0x01
MAD_METHOD_SET = 0x02
MAD_METHOD_SEND = 0x03
MAD_METHOD_GET_RESP = 0x81
MAD_METHOD_TRAP = 0x05
MAD_METHOD_TRAP_REPRESS = 0x07
MAD_METHOD_GET_TABLE = 0x12
MAD_METHOD_GET_TRACE_TABLE = 0x13
MAD_METHOD_GET_MULTI = 0x14
MAD_METHOD_DELETE = 0x15
MAD_METHOD_RESPONSE = 0x80

methodMap = {}
prefix = (
    "Subn",
    "CommMgt",
    "Performance",
    "BM",
    "DevMgt",
    "SubnAdm",
    "SNMP",
    "Vend",
)


for cur_p in prefix:
    for cur_name in (
        "Get",
        "Set",
        "Send",
        "Trap",
        "Delete",
    ):
        methodMap[cur_p + cur_name] = "MAD_METHOD_{}".format(cur_name.upper())
    methodMap[cur_p + "TrapRepress"] = "MAD_METHOD_TRAP_REPRESS"
    methodMap[cur_p + "GetTable"] = "MAD_METHOD_GET_TABLE"
    methodMap[cur_p + "GetTraceTable"] = "MAD_METHOD_GET_TRACE_TABLE"
    methodMap[cur_p + "GetMulti"] = "MAD_METHOD_GET_MULTI"


@contextmanager
def safe_update_ctx(path: str):
    """Open a temporary file path.tmp, return it, then close it and rename it
    to path using safeUpdate as a context manager"""
    tmp = path + ".tmp"
    try:
        os.unlink(tmp)
    except Exception:
        pass

    l_f_obj = open(tmp, "wt")
    yield l_f_obj
    l_f_obj.close()
    os.rename(tmp, path)


def rst_tableize(rst_lst, idx):
    width = max(len(i[idx]) for i in rst_lst)
    line = "=" * width
    yield line
    first = True
    for idx in rst_lst:
        yield idx[idx].ljust(width)
        if first:
            yield line
            first = False
    yield line


class Type(object):
    """Hold a single typed field in the structure"""
    mutable = True

    def __init__(self, in_xml, off):
        self.count = int(in_xml.get("count", "1"))
        self.bits = int(in_xml.get("bits"))
        self.off = in_xml.get("off")
        self.fmt = in_xml.get("display")
        if self.fmt == "data":
            self.fmt = None
        if self.fmt == "string":
            self.fmt = "str"
        if self.fmt is None:
            self.fmt = "%r"
        if self.off is not None:
            g = re.match("^(\d+)\[(\d+)\]$", self.off)
            if g:
                g = g.groups()
                self.off = int(g[0]) * 8 + int(g[1])
            else:
                self.off = int(self.off) * 8
            assert self.off == off
        else:
            self.off = off

        self.in_comp_mask = int(in_xml.get("comp_mask", "1")) != 0

        self.type = in_xml.get("type")
        if self.type == "HdrIPv6Addr" and self.bits == 128:
            self.type = "struct IBA.GID"
            self.mutable = False
        if self.type is None and in_xml.text is not None and self.bits == 64 and "GUID" in in_xml.text:
            self.type = "struct IBA.GUID"
            self.mutable = False

    def len_bits(self) -> int:
        return self.bits * self.count

    def is_object(self) -> bool:
        return self.type and self.type.startswith("struct ")

    def init_str(self) -> str:
        base = "0"
        if self.is_object():
            base = self.type[7:] + "()"
        elif self.bits > 64:
            base = "bytearray(%u)" % (self.bits / 8)
        if self.count != 1:
            if self.bits == 8:
                return "bytearray(%u)" % (self.count)
            if self.is_object():
                return "[%s for I in range(%u)]" % (base, self.count)
            return "[%s]*%u" % (base, self.count)
        return base

    def type_desc(self) -> str:
        base = ":class:`int`"
        if self.is_object():
            ty = self.type[7:]
            if ty.startswith("IBA."):
                base = ":class:`~rdma.%s`" % (self.type[7:])
            else:
                base = ":class:`~rdma.IBA.%s`" % (self.type[7:])
        elif self.bits > 64:
            base = ":class:`bytearray` (%u)" % (self.bits / 8)
        if self.count != 1:
            if self.bits == 8:
                base = ":class:`bytearray` ({:d})".format(self.count)
            return "[%s]*%u" % (base, self.count)
        return base

    def make_pack(self, name, idx=0) -> str:
        return "%s.pack_into(buffer,offset + %u)" % (name, self.off / 8 + idx * self.bits / 8)

    def make_unpack(self, name, idx=0):
        if self.mutable:
            return "%s.unpack_from(buffer,offset + %u)" % (name, self.off / 8 + idx * self.bits / 8)
        return "%s = %s(buffer[offset + %u:offset + %u],raw=True)" % \
               (name, self.type[7:], self.off / 8 + idx * self.bits / 8,
                self.off / 8 + (idx + 1) * self.bits / 8)

    def isAligned(self):
        if self.bits >= 32:
            return self.bits % 32 == 0 and self.off % 32 == 0
        return (self.bits == 8 or self.bits == 16) and \
               (self.off % self.bits) == 0

    def getStruct(self):
        if self.is_object():
            return self.type[7:]
        return None


class Struct(object):
    """
    Holds the a single structure
    """

    def __init__(self, xml, fn):
        self.filename = fn
        self.name = xml.get("name")
        self.size = int(xml.get("bytes"))
        self.desc = "%s (section %s)" % (xml.get("desc"), xml.get("sect"))
        self.sect = tuple(I for I in xml.get("sect", "").split("."))

        self.mgmtClass = xml.get("mgmtClass")
        self.mgmtClassVersion = xml.get("mgmtClassVersion")
        self.methods = xml.get("methods")
        if self.methods is not None:
            self.methods = set(self.methods.split())
        else:
            self.methods = set()

        self.attributeID = xml.get("attributeID")
        if self.attributeID is not None:
            self.attributeID = int(self.attributeID, 0)

        self.is_format = (self.name.endswith("Format") or
                          self.name.endswith("FormatDirected"))
        self.format = xml.get("format")

        self.inherits = {}
        self.mb = []
        self.packCount = 0

        off = 0
        for cur_el in xml.getiterator("mb"):
            self.mb.append((cur_el.text or "", Type(cur_el, off)))
            off = off + self.mb[-1][1].len_bits()
        assert (sum((cur_el[1].len_bits() for cur_el in self.mb), 0) <= self.size * 8)

    def set_reserved(self):
        def to_reserved(s, ty):
            if not s:
                self.reserved = self.reserved + 1
                return "reserved_{:d}".format(ty.off)
            return s

        self.reserved = 0
        self.mb = [(to_reserved(name, ty), ty) for name, ty in self.mb]
        self.mbGroup = self.groupMB()

    def make_inherit(self):
        """*Format structures inherit from the first element, but
        we optimize the codegen a little bit..."""
        if not self.is_format and not self.name == "SAHeader":
            return

        first = self.mb[0]
        if not (first[0].endswith("Header") and first[1].is_object()):
            return
        parent = structMap[first[1].getStruct()]

        # replace the contents of the top struct into our mb list
        self.mb = parent.mb + self.mb[1:]
        self.inherits[first[0]] = parent

        # FIXME: I would like it if this was actually done with some
        # inheritance so that isinstance would work properly, but since we use
        # slots that seems like it would just cause confusion.  Certainly the
        # codegen of a single pack/unpack is very desirable.

        assert (sum((cur_el[1].len_bits() for cur_el in self.mb), 0) <= self.size * 8)
        self.make_inherit()

    def gen_component_mask(self, follow=True):
        """We have an automatic system for managing the component mask value
        used in SA queries. This generates the component mask bit offsets."""
        res = []
        for name, mbt in sorted(self.mb, key=lambda x: x[1].off):
            struct = mbt.getStruct()
            if follow and struct is not None and struct in structMap:
                tmp = structMap[struct].gen_component_mask(False)
                res.extend("%s.%s" % (name, J) for J in tmp)
            elif mbt.in_comp_mask:
                # serviceData is special, each array elements gets a mask.
                if name.startswith("serviceData"):
                    for idx in range(mbt.count):
                        res.append(name + "_{:d}".format(idx))
                else:
                    res.append(name)
        return res

    def groupMB(self):
        """Take the member list and group it into struct format characters. We
        try to have 1 format character for each member, but if that doesn't
        work out we group things that have to fit into a 8, 16 or 32 bit
        word."""

        groups = []
        curGroup = []
        off = 0
        for mb_s in self.mb:
            bits = mb_s[1].len_bits()
            if bits == 0:
                continue
            curGroup.append(mb_s)

            if (off == 0 and (off + bits) % 32 == 0) or \
                (off + bits) % 32 == 0:
                if reduce(lambda a, b: a and b[1].isAligned(), curGroup, True):
                    for _group in curGroup:
                        groups.append((_group,))
                else:
                    groups.append(curGroup)
                curGroup = []
                off = 0
                continue
            off = off + bits
        assert (not curGroup)
        return groups

    def bitsToFormat(self, bits):
        if bits == 8:
            return "B"
        if bits == 16:
            return "H"
        if bits == 32:
            return "L"
        if bits == 64:
            return "Q"
        assert (False)

    def formatSinglePack(self, bits, name, mbt):
        other = mbt.getStruct()
        if other:
            if mbt.count == 1:
                return (None, (mbt.make_pack(name),
                               mbt.make_unpack(name)),
                        mbt.len_bits())
            lst = []
            for idx in range(0, mbt.count):
                n = "{}[{:d}]".format(name, idx)
                lst.append(
                    (
                        None,
                        (
                            mbt.make_pack(n, idx),
                            mbt.make_unpack(n, idx),
                        ),
                        mbt.len_bits(),
                    )
                )
            return lst
        if mbt.type == "HdrIPv6Addr":
            return "[:16]", name, bits
        if mbt.count == 1:
            if mbt.type is None and bits > 64:
                return "[:%u]" % (bits / 8), name, bits
            else:
                return self.bitsToFormat(bits), name, bits
        if mbt.bits == 8:
            return "[:%u]" % (bits / 8), name, bits
        if mbt.bits == 16 or mbt.bits == 32:
            res = []
            for idx in range(0, mbt.count):
                res.append(
                    (
                        self.bitsToFormat(mbt.bits),
                        "{}[{:d}]".format(name, idx),
                        mbt.bits,
                    )
                )
            return res

        # Must be a bit array
        assert (bits % 8 == 0)
        return (
            None,
            (
                "rdma.binstruct.pack_array8(buffer,offset+{:d},{:d},{:d},{})".format(
                    mbt.off / 8,
                    mbt.bits,
                    mbt.count,
                    name,
                ),
                "rdma.binstruct.unpack_array8(buffer,offset+{:d},{:d},{:d},{})".format(
                    mbt.off / 8,
                    mbt.bits,
                    mbt.count,
                    name,
                )
            ),
            bits,
        )

    def structFormat(self, groups, prefix):
        res = []
        for _group in groups:
            bits = sum(cur_g[1].len_bits() for cur_g in _group)
            assert (bits == 8 or bits == 16 or bits == 32 or bits % 32 == 0)
            if len(_group) == 1:
                x = self.formatSinglePack(bits, prefix + _group[0][0], _group[0][1])
                if isinstance(x, list):
                    res.extend(x)
                else:
                    res.append(x)
                continue

            func = "_pack_%u_%u" % (self.packCount, bits)
            self.packCount = self.packCount + 1

            pack = ["@property", "def %s(self):" % (func)]
            unpack = ["@%s.setter" % (func), "def %s(self,value):" % (func)]
            tmp = []
            off = bits
            for J in _group:
                off = off - J[1].bits
                tmp.append("((%s%s & 0x%X) << %u)" % (prefix, J[0], (1 << J[1].bits) - 1, off))
                unpack.append("    %s%s = (value >> %u) & 0x%X;" % (prefix, J[0], off, (1 << J[1].bits) - 1))
            pack.append("    return %s" % (" | ".join(tmp)))
            self.funcs.append(pack)
            self.funcs.append(unpack)

            res.append((self.bitsToFormat(bits), "self.%s" % (func), bits))
        return res

    def genFormats(self, fmts, pack, unpack):
        """Split into struct processing blocks and byte array assignment
        blocks"""
        off = 0
        sfmts = [[]]
        sfmtsOff = []
        fmtsOff = 0
        for idx in fmts:
            if idx[0] is None:
                pack.append("    %s;" % (idx[1][0]))
                unpack.append("    %s;" % (idx[1][1]))
                off = off + idx[2]
                continue
            if idx[0][0] == "[":
                assert off % 8 == 0 and idx[2] % 8 == 0
                pack.append("    buffer[offset + %u:offset + %u] = %s" % \
                            (off / 8, off / 8 + idx[2] / 8, idx[1]))
                unpack.append("    %s = bytearray(buffer[offset + %u:offset + %u])" % \
                              (idx[1], off / 8, off / 8 + idx[2] / 8))
                off = off + idx[2]
                continue
            if fmtsOff != off and sfmts[-1]:
                sfmts.append([])

            if not sfmts[-1]:
                sfmtsOff.append(off)
            sfmts[-1].append(idx)
            off = off + idx[2]
            fmtsOff = off

        for idx, off in zip(sfmts, sfmtsOff):
            pack.append(
                "    struct.pack_into('>{}',buffer,offset+{:d},{});".format(
                    "".join(J[0] for J in idx),
                    off / 8,
                    ",".join(J[1] for J in idx),
                ),
            )
            unpack.append(
                "    ({},) = struct.unpack_from('>{}',buffer,offset+{:d});".format(
                    ",".join(J[1] for J in idx),
                    "".join(J[0] for J in idx),
                    off / 8,
                ),
            )

    def get_properties(self):
        yield "MAD_LENGTH", "%u" % (self.size)
        if self.mgmtClass:
            yield "MAD_CLASS", "0x%x" % (int(self.mgmtClass, 0))
            yield "MAD_CLASS_VERSION", "0x%x" % (int(self.mgmtClassVersion, 0))
        if self.format:
            yield "FORMAT", self.format
        if self.attributeID is not None:
            yield "MAD_ATTRIBUTE_ID", "0x%x" % (self.attributeID)
        if self.methods and not self.is_format:
            is_sa = False
            for cur_method in sorted(self.methods):
                if cur_method.startswith("SubnAdm"):
                    is_sa = True
                yield "MAD_{}".format(
                    cur_method.upper()
                ), "0x{:x} # {}".format(
                    globals()[methodMap[cur_method]],
                    methodMap[cur_method],
                )
            if is_sa:
                cm = self.gen_component_mask()
                if cm:
                    yield "COMPONENT_MASK", "{{{}}}".format(
                        ", ".join("{!r}:{:d}".format(cm_name, idx) for idx, cm_name in enumerate(cm)),
                    )
        yield "MEMBERS", "[{}]".format(
            ", ".join(
                "({!r},{!r},{!r})".format(_name, ty.bits, ty.count) for _name, ty in self.mb if ty.bits != 0
            )
        )

    def asPython(self, F):
        self.funcs = []

        if self.mb:
            x = ["def __init__(self,*args):"]
            for name, ty in self.mb:
                if (ty.is_object() and ty.mutable) or ty.count != 1:
                    x.append("    self.%s = %s;" % (name, ty.init_str()))
            if len(x) != 1:
                x.append("    rdma.binstruct.BinStruct.__init__(self,*args);")
                self.funcs.append(x)
            x = ["def zero(self):"]
            for name, ty in self.mb:
                if ty.len_bits() != 0:
                    x.append("    self.%s = %s;" % (name, ty.init_str()))
            self.funcs.append(x)

        pack = ["def pack_into(self,buffer,offset=0):"]
        unpack = ["def unpack_from(self,buffer,offset=0):"]
        fmts = self.structFormat(self.mbGroup, "self.")
        if fmts:
            self.genFormats(fmts, pack, unpack)
        else:
            pack.append("    return None;")
            unpack.append("    return;")
        self.funcs.append(pack)
        self.funcs.append(unpack)

        self.slots = ','.join(repr(I[0]) for I in self.mb if I[1].len_bits() != 0)
        if self.is_format:
            print("class %s(rdma.binstruct.BinFormat):" % (self.name), file=F)
        else:
            print("class %s(rdma.binstruct.BinStruct):" % (self.name), file=F)
        print("    '''%s'''" % (self.desc), file=F)
        print("    __slots__ = (%s);""" % (self.slots), file=F)

        for name, value in self.get_properties():
            print("    %s = %s" % (name, value), file=F)

        for I in self.funcs:
            print("   ", "\n    ".join(I), file=F)
            print(file=F)

    def as_RST_pos(self, off):
        if off % 8 == 0:
            return "%u" % (off // 8)
        return "%u[%u]" % (off // 8, off % 8)

    def asRST(self, F):
        print(".. class:: rdma.IBA.%s" % (self.name), file=F)
        print("", file=F)
        if self.inherits:
            print("    An *aggregation* of: %s" % (", ".join(I.name for I in self.inherits.values())), file=F)
            print("", file=F)
        print("   ", self.desc, file=F)
        print("", file=F)
        for p_name, value in self.get_properties():
            print("    .. attribute:: %s = %s" % (p_name, value), file=F)
        print("", file=F)

        rows = [("Member", "Position", "Type")]
        for p_name, ty in self.mb:
            rows.append((":attr:`%s`" % (p_name),
                         "%s:%s (%u)" % (self.as_RST_pos(ty.off),
                                         self.as_RST_pos(ty.off + ty.len_bits()),
                                         ty.bits),
                         ty.type_desc()))
        if rows:
            for I in zip(rst_tableize(rows, 0), rst_tableize(rows, 1), rst_tableize(rows, 2)):
                print("   ", " ".join(I), file=F)
            print("", file=F)


parser = optparse.OptionParser(usage="%prog")
parser.add_option('-x', '--xml', dest='xml', action="append")
parser.add_option('-o', '--struct-out', dest='struct_out')
parser.add_option('-r', '--rst-out', dest='rst_out')
(options, args) = parser.parse_args()

structs = []
for cur_p in options.xml:
    with open(cur_p, 'r') as f_obj:
        doc = ElementTree.parse(f_obj)
        for xml in doc.findall("struct"):
            if not xml.get("containerName"):
                structs.append(Struct(xml, cur_p))
structMap = dict((I.name, I) for I in structs)
for cur_p in structs:
    for cur_name in cur_p.mb:
        obj = structMap.get(cur_name[1].getStruct())
        if obj is not None:
            assert obj.size * 8 == cur_name[1].bits
for cur_p in structs:
    cur_p.make_inherit()
for cur_p in structs:
    cur_p.set_reserved()

# Match up formats and attributes. We infer the matching based on grouping in a file.
for cur_p in structs:
    if cur_p.is_format:
        cur_p.attributes = set()
        for cur_name in structs:
            if cur_name.format is not None and cur_name.format != cur_p.name:
                continue
            if cur_name.filename == cur_p.filename and cur_name.attributeID is not None:
                cur_p.attributes.add(cur_name)
        for cur_name in cur_p.attributes:
            if cur_name.methods:
                cur_p.methods.update(cur_name.methods)

with safe_update_ctx(options.struct_out) as f_obj:
    to_import = {"struct", "rdma.binstruct"}
    for cur_p in structs:
        if cur_p.format is not None:
            p = cur_p.format.rpartition('.')
            if p[0]:
                to_import.add(p[0])
    print("import %s" % (",".join(sorted(to_import))), file=f_obj)
    for cur_p in structs:
        cur_p.asPython(f_obj)

    fmts = {}
    for cur_p in structs:
        for cur_name in cur_p.mb:
            if cur_name[0].startswith("reserved"):
                continue
            assert fmts.get(cur_name[0], cur_name[1].fmt) == cur_name[1].fmt
            if cur_name[1].fmt != "%r":
                fmts[cur_name[0]] = cur_name[1].fmt
    print("MEMBER_FORMATS = {!r};".format(fmts), file=f_obj)

    res = (I for I in structs if I.is_format)
    print("CLASS_TO_STRUCT = {%s};" % (",\n\t".join("(%u,%u):%s" % (
        int(I.mgmtClass, 0), (1 << 8) | int(I.mgmtClassVersion, 0), I.name) for I in res)), file=f_obj)

    res = {}
    for cur_p in structs:
        if cur_p.is_format:
            for cur_name in structs:
                if cur_name.attributeID is not None and not cur_p.methods.isdisjoint(cur_name.methods):
                    res[cur_p.name, cur_name.attributeID] = cur_name
    for cur_p in structs:
        if cur_p.format is not None and cur_p.attributeID is not None:
            res[cur_p.format, cur_p.attributeID] = cur_p
    print(
        "ATTR_TO_STRUCT = {{{}}};".format(
            ",\n\t".join(
                "({},{:d}):{}".format(
                    k[0],
                    k[1],
                    v.name,
                ) for k, v in sorted(res.items())
            )
        ),
        file=f_obj,
    )

if options.rst_out is not None:
    with safe_update_ctx(options.rst_out) as f_obj:
        def is_sect_prefix(x, y):
            return x == y[:len(x)]


        sects = [
            (("12",), "Communication Management"),
            (("13", "4"), "Generic MAD"),
            (("13", "6"), "RMPP"),
            (("14",), "Subnet Management"),
            (("15",), "Subnet Administration"),
            (("16", "1"), "Performance Management"),
            (("A13", "6"), "Performance Management"),
            (("16", "3"), "Device Management"),
            (("16", "4"), "SNMP Tunneling"),
            (("16", "5"), "Vendor Specific Management"),
        ]
        lst = sorted(structs, key=lambda x: x.name)
        done = set()
        last = None
        for cur_p, name in sects:
            if name != last:
                header = "{} ({})".format(
                    name,
                    ".".join("{}".format(_p) for _p in cur_p),
                )
                print(header, file=f_obj)
                print("^" * len(header), file=f_obj)
                print(file=f_obj)
                last = name
            for cur_name in lst:
                if cur_name not in done and is_sect_prefix(cur_p, cur_name.sect):
                    cur_name.asRST(f_obj)
                    done.add(cur_name)

        header = "Miscellaneous IBA Structures"
        print(header, file=f_obj)
        print("^" * len(header), file=f_obj)
        print(file=f_obj)
        for cur_name in lst:
            if cur_name not in done:
                cur_name.asRST(f_obj)
