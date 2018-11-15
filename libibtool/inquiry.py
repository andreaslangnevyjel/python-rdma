# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.
# -*- coding: utf-8 -*-
# Fairly simple status/inquery commands

import copy
import struct
import codecs

import rdma.IBA as IBA
import rdma.IBA_describe as IBA_describe
import rdma.binstruct
import rdma.madtransactor
import rdma.satransactor
from libibtool.libibopts import *


def cmd_ibv_devices(argv, o):
    """Display the RDMA devices in the system.
       Usage: %prog"""
    _args, _values = o.parse_args(argv, expected_values=0)

    print(
        "    {:<16s}t    node GUID".format("device"),
    )
    print(
        "    {:<16s}\t-------------------".format("------"),
    )
    for cur_dev in rdma.get_devices():
        print(
            "    {:<16s}\t{}".format(cur_dev.name, cur_dev.node_guid),
        )
    return True


def cmd_ibstat(argv, o):
    """Display the RDMA end ports in the system.
       Usage: %prog [-lsp] [DEVICE [PORT]]"""
    o.add_option(
        "-l",
        "--list_of_cas",
        action="store_true",
        dest="list_cas",
        help="List all IB devices names",
    )
    o.add_option(
        "-s",
        "--short",
        action="store_true",
        dest="short",
        help="Do not show port information",
    )
    o.add_option(
        "-p",
        "--port_list",
        action="store_true", dest="ports",
        help="Show only port GUIDs",
    )
    args, values = o.parse_args(argv)

    if args.list_cas:
        if len(values) != 0:
            raise CmdError("Too many arguments")
        for cur_p in rdma.get_devices():
            print(cur_p.name)
        return True

    if len(values) == 0:
        end_ports = (
            cur_port for cur_dev in rdma.get_devices() for cur_port in cur_dev.end_ports
        )
    elif len(values) == 1:
        end_ports = (
            e_port for e_port in rdma.get_device(values[0]).end_ports
        )
    elif len(values) == 2:
        end_ports = (
            rdma.get_end_port("{}/{}".format(values[0], values[1])),
        )
    else:
        raise CmdError("Too many arguments")

    if args.ports:
        for cur_p in end_ports:
            print(cur_p.port_guid)
        return True

    def show_ca(dev):
        print("CA {!r}".format(dev.name))
        print("\tCA type: {}".format(dev.hca_type))
        print("\tNumber of ports: %s" % (len(dev.end_ports)))
        print("\tFirmware version: %s" % (IBA_describe.dstr(dev.fw_ver)))
        print("\tHardware version: %s" % (IBA_describe.dstr(dev.hw_ver)))
        print("\tNode GUID: %s" % (dev.node_guid))
        print("\tSystem image GUID: %s" % (dev.sys_image_guid))

    def show_port(port, offset="\t\t"):
        print("%sState: %s" % (offset, IBA_describe.link_state(port.state)))
        print("%sPhysical state: %s" % (offset, IBA_describe.phys_link_state(port.phys_state)))
        print("%sRate: %r" % (offset, port.rate))
        print("%sBase lid: %r" % (offset, port.lid))
        print("%sLMC: %r" % (offset, port.lmc))
        print("%sSM lid: %r" % (offset, port.sm_lid))
        print("%sCapability mask: 0x%08x" % (offset, port.cap_mask))
        print("%sPort GUID: %s" % (offset, port.port_guid))

    last_ca = None
    if args.short:
        for cur_p in end_ports:
            if last_ca != cur_p.parent:
                show_ca(cur_p.parent)
                last_ca = cur_p.parent
        return True

    if isinstance(end_ports, tuple):
        cur_p = end_ports[0]
        print("CA: %r" % (cur_p.parent.name))
        print("Port %u:" % (cur_p.port_id))
        show_port(cur_p, offset="")
        return True

    for cur_p in end_ports:
        if last_ca != cur_p.parent:
            show_ca(cur_p.parent)
            last_ca = cur_p.parent
        print("\tPort %u:" % (cur_p.port_id))
        show_port(cur_p)
    return True


def cmd_ibstatus(argv, o):
    """Display the RDMA end ports in the system.
       Usage: %prog [DEVICE[/PORT]]"""
    (args, values) = o.parse_args(argv)

    if len(values) == 0:
        end_ports = (I for J in rdma.get_devices() for I in J.end_ports)
    elif len(values) == 1:
        end_ports = (rdma.get_end_port(values[0]),)
    else:
        raise CmdError("Too many arguments")

    for I in end_ports:
        print("""Infiniband device %r port %u status:
\tdefault gid:\t %s
\tbase lid:\t %u
\tsm lid:\t\t %u
\tstate:\t\t %u: %s
\tphys state:\t %u: %s
\trate:\t\t %s\n""" % (I.parent.name, I.port_id, I.default_gid, I.lid, I.sm_lid,
                       I.state, IBA_describe.link_state(I.state).upper(),
                       I.phys_state, IBA_describe.phys_link_state(I.phys_state), I.rate))
    return True


def cmd_ibaddr(argv, o):
    """Display the GID and LID addresses for end ports.
       Usage: %prog [-glL] [TARGET]"""
    o.add_option("-l", "--lid_show", action="store_true", dest="lid",
                 help="Show LID information")
    o.add_option("-L", "--Lid_show", action="store_true", dest="lid",
                 help="Show LID information")
    o.add_option("-g", "--gid_show", action="store_true", dest="gid",
                 help="Show GID information")
    LibIBOpts.setup(o)
    (args, values) = o.parse_args(argv)
    lib = LibIBOpts(o, args, values, 1, (tmpl_target,))

    if not values:
        values = (None,)

    if args.lid is None and args.gid is None:
        args.lid = True
        args.gid = True

    with lib.get_umad_for_target(values[0]) as umad:
        path = lib.path
        ninf = umad.subn_get(IBA.SMPNodeInfo, path)
        path.DGID = IBA.GID(prefix=IBA.GID_DEFAULT_PREFIX, guid=ninf.portGUID)
        pinf = umad.subn_get(IBA.SMPPortInfo, path, 0)

        if args.gid:
            print("GID {}".format(path.DGID), end=' ')
        if args.lid:
            print(
                "LID start {:d} end {:d}".format(
                    pinf.LID,
                    pinf.LID + (1 << pinf.LMC) - 1,
                ),
                end=' ',
            )
        print()
    return lib.done()


methods = {
    "subn_get",
    "performance_get",
    "subn_adm_get",
    "subn_adm_get_table",
    "bm_get",
    "comm_mgt_get",
    "dev_mgt_get",
    "snmp_get",
}

methods.intersection_update(dir(rdma.madtransactor.MADTransactor))


def is_valid_attribute(attr) -> bool:
    if getattr(attr, "MAD_LENGTH", None) is None or getattr(attr, "MAD_ATTRIBUTE_ID", None) is None:
        return False
    for meth in methods:
        if getattr(attr, "MAD_{}".format(meth.upper()), None) is not None:
            return True
    print("*", methods)
    return False


def tmpl_method(v):
    if v not in methods:
        raise CmdError("Invalid method {!r}".format(v))
    return v


def tmpl_attribute(v):
    attr = getattr(rdma.IBA, v, None)
    if attr is None:
        raise CmdError("Invalid attribute {!r}".format(v))
    if not is_valid_attribute(attr):
        raise CmdError("Invalid attribute {!r}".format(v))
    return attr


def cmd_query_help(o, cmd, usage) -> str:
    """Generate the help text by merging in information from OPS."""

    def get_attrs():
        for k, v in rdma.IBA.__dict__.items():
            if is_valid_attribute(v):
                yield k

    return "".join(
        [
            usage,
            "\n    Valid METHOD:\n    ",
            "\n    ".join(
                "   {}".format(cur_meth) for cur_meth in sorted(methods)
            ),
            "\n    Valid ATTRIBUTE:\n    ",
            "\n    ".join(
                "   {}".format(cur_attr) for cur_attr in sorted(get_attrs())
            ),
        ],
    )


def cmd_query(argv, o):
    """Issue any GET type query for any known attribute
       Usage: %prog METHOD ATTRIBUTE [TARGET]

       Eg:
          %prog PerformanceGet PMPortCounters -f portSelect=1
          %prog SubnAdmGet SAPathRecord -f SGID=fe80::0002:c903:0000:1491 -f DGID=fe80::0002:c903:0000:1492
          """
    import libibtool.saquery

    o.add_option("-a", "--attribute-id", action="store", dest="attribute_id",
                 default=0, type=int,
                 help="Set the attribute ID field in the request MAD")
    o.add_option("-f", "--field", action="append", dest="fields",
                 default=[],
                 help="Set the given field in the request MAD.")
    LibIBOpts.setup(o)
    (args, values) = o.parse_args(argv)
    lib = LibIBOpts(o, args, values, 3, (tmpl_method, tmpl_attribute, tmpl_target))

    if len(values) == 2:
        values.append("")
    if len(values) < 3:
        raise CmdError("Too few arguments")

    with lib.get_umad_for_target(
        values[2],
        gmp=(values[0] != "subn_get"),
    ) as umad:
        meth = getattr(umad, values[0])
        req = values[1]()
        if values[0].startswith("subn_adm"):
            req = IBA.ComponentMask(req)
        for cur_f in args.fields:
            try:
                n, v = cur_f.split("=")
            except ValueError:
                raise CmdError("Field {!r} does not have exactly 1 equals.".format(cur_f))
            libibtool.saquery.set_mad_attr(req, n, v)
        ret = meth(req, lib.path, args.attribute_id)
        if isinstance(ret, list):
            out = libibtool.saquery.Indentor(sys.stdout)
            for num, cur_f in enumerate(ret):
                print("Reply structure #{:d}".format(num))
                cur_f.printer(out, **lib.format_args)
        else:
            ret.printer(sys.stdout, **lib.format_args)
    return lib.done()


def cmd_sminfo(argv, o):
    """Display the SASMInfo record for a subnet manager.
       Usage: %prog [TARGET [ATTR_MOD]]

       This command includes the ability to send a SubnSet(SASMInfo)
       packet formed with a given priority, state, SMKey and Attribute
       Modifier. A set is performed if a ATTR_MOD is provided. See IBA 14.4.1."""
    o.add_option(
        "-s",
        "--state",
        action="store",
        dest="state",
        type="int",
        help="Set the SM state",
    )
    o.add_option(
        "-p",
        "--priority",
        action="store",
        dest="priority",
        type="int",
        help="Set the SM priority",
    )
    o.add_option(
        "--sminfo_smkey",
        action="store",
        dest="sminfo_smkey",
        type="int",
        default=0,
        help="Use this value for the SMPSMInfo.SMKey",
    )
    LibIBOpts.setup(o)
    (args, values) = o.parse_args(argv)
    lib = LibIBOpts(o, args, values, 2, (tmpl_target, tmpl_int))

    if not values:
        values = (None,)

    with lib.get_umad_for_target(values[0]) as umad:
        if values[0]:
            path = lib.path
        else:
            path = umad.end_port.sa_path.copy(dqpn=0, qkey=IBA.IB_DEFAULT_QP0_QKEY)

        sinf = IBA.SMPSMInfo()
        if args.smkey is not None:
            sinf.SMKey = args.sminfo_smkey
        sinf = umad.subn_get(sinf, path)
        smlid = path.DLID
        if smlid == IBA.LID_PERMISSIVE:
            smlid = umad.subn_get(IBA.SMPPortInfo, path).LID
        print(
            "sminfo: sm lid {:d} sm guid {}, activity count {:d} priority {:d} state {:d}".format(
                smlid,
                sinf.GUID,
                sinf.actCount,
                sinf.priority,
                sinf.SMState,
            ),
        )

        if args.smkey is not None:
            sinf.SMKey = args.smkey
        if len(values) == 2:
            if args.state is not None:
                sinf.SMState = args.state
            if args.priority is not None:
                sinf.priority = args.priority
            amod = values[1]
            sinf = umad.subn_set(sinf, path, amod)
            print(
                "sminfo: sm lid {:d} sm guid {}, activity count {:d} priority {:d} state {:d}".format(
                    smlid,
                    sinf.GUID,
                    sinf.actCount,
                    sinf.priority,
                    sinf.SMState,
                ),
            )
    return lib.done()


def cmd_smpdump(argv, o):
    """Display an arbitrary SMP record
       Usage: %prog TARGET ATTR [ATTR_MOD]

       ATTR is the attribute ID and ATTR_MOD is an optional modifier."""
    o.add_option("-p", "--decode", action="store_true", dest="decode",
                 help="Pretty print the entire reply.")
    LibIBOpts.setup(o)
    args, values = o.parse_args(argv)
    lib = LibIBOpts(o, args, values, 3, (tmpl_target, tmpl_int, tmpl_int))

    if len(values) < 2:
        raise CmdError("Too few arguments")

    with lib.get_umad_for_target(values[0]) as umad:
        path = lib.path

        class Dummy(rdma.binstruct.BinStruct):
            buf = None

            def unpack_from(self, buf, offset=0):
                self.buf = buf[offset:]
                pass

            def pack_into(self, buf, offset=0):
                pass

        setattr(Dummy, "MAD_ATTRIBUTE_ID", values[1])
        setattr(Dummy, "MAD_SUBNGET", IBA.MAD_METHOD_GET)
        payload = Dummy
        res = umad.subn_get(payload, path, values[2] if len(values) >= 3 else 0)
        if args.decode:
            umad.reply_fmt.printer(sys.stdout)
        else:
            assert (len(res.buf) % 4 == 0)
            ret = codecs.encode(res.buf, "hex")

            for entry in range(int(len(ret) / 4)):
                print(ret[entry * 4:entry * 4 + 4], end=' ')
                if (entry + 1) % 8 == 0:
                    print()
            if (entry + 1) % 8 != 0:
                print()
            print(
                "SMP status: 0x{:04x}".format(
                    umad.reply_fmt.status | (umad.reply_fmt.D << 15),
                ),
            )
    return lib.done()


def cmd_ibportstate(argv, o):
    """
    Manipulate the SMPPortInfo of a port
    Usage: %prog TARGET PORTNUM OP [OP_ARG]

    OP is one of enable, disable, reset, speed, width, query.
    """
    LibIBOpts.setup(o)
    args, values = o.parse_args(argv, )
    lib = LibIBOpts(o, args, values, 4, (tmpl_target, tmpl_int, str, tmpl_int))

    if len(values) < 3:
        raise CmdError("Too few arguments")

    with lib.get_umad_for_target(values[0]) as umad:
        path = lib.path

        port_idx = values[1]
        if isinstance(umad, rdma.satransactor.SATransactor):
            pinf = umad._parent.subn_get(IBA.SMPPortInfo, path, port_idx)
        else:
            pinf = umad.subn_get(IBA.SMPPortInfo, path, port_idx)

        if isinstance(path, rdma.path.IBDRPath):
            peer_path = path.copy()
            peer_path.drPath += chr(port_idx)
        else:
            peer_path = rdma.path.IBDRPath(
                path.end_port,
                SLID=path.SLID,
                drSLID=path.SLID,
                DLID=path.DLID,
                drPath=b"\0" + chr(port_idx),
            )
        if pinf.portState != IBA.PORT_STATE_DOWN:
            peer_pinf = umad.subn_get(IBA.SMPPortInfo, peer_path, port_idx)
        else:
            peer_pinf = None

        # NOP the modification pinf.
        mpinf = copy.copy(pinf)
        mpinf.portState = 0
        mpinf.portPhysicalState = 0
        mpinf.linkSpeedEnabled = 0
        mpinf.linkWidthEnabled = 0

        if values[2] == "query":
            if peer_pinf is not None:
                print(
                    "# Port info: Lid {:d} port {:d} (peer is Lid {:d} port {:d})".format(
                        pinf.LID,
                        pinf.local_port_num,
                        peer_pinf.LID,
                        peer_pinf.local_port_num,
                    ),
                )
            else:
                print(
                    "# Port info: Lid {:d} port {:d}".format(
                        pinf.LID,
                        pinf.local_port_num,
                    ),
                )
            pinf.printer(sys.stdout, **lib.format_args)
        elif values[2] == "enable" or values[2] == "reset":
            mpinf.portPhysicalState = IBA.PHYS_PORT_STATE_POLLING
            umad.subn_set(mpinf, path, port_idx)
        elif values[2] == "disable":
            mpinf.portPhysicalState = IBA.PHYS_PORT_STATE_DISABLED
            umad.subn_set(mpinf, path, port_idx)
        elif values[2] == "speed":
            mpinf.linkSpeedEnabled = values[3]
            umad.subn_set(mpinf, path, port_idx)
        elif values[2] == "width":
            mpinf.linkWidthEnabled = values[3]
            umad.subn_set(mpinf, path, port_idx)
        else:
            raise CmdError("Operation {!r} is not known".format(values[3]))
    return lib.done()


def decode_link(o, bytes):
    """Assume bytes starts with the LRH and parse accordingly. Returns bytes
       starting at the MAD header"""
    lhdr = IBA.HdrLRH(bytes)
    off = 8
    if o.verbosity >= 1:
        lhdr.printer(sys.stdout)
    if lhdr.LNH & 1 == 1:
        ghdr = IBA.HdrGRH(bytes[off:])
        if o.verbosity >= 1:
            ghdr.printer(sys.stdout)
        off = off + 40
    bth = IBA.HdrBTH(bytes[off:])
    if o.verbosity >= 1:
        bth.printer(sys.stdout)
    off = off + 12
    if bth.service == 3 and bth.function == 4:
        deth = IBA.HdrDETH(bytes[off:])
        if o.verbosity >= 1:
            deth.printer(sys.stdout)
        off = off + 8
    return bytes[off:]


class UMADHdr(rdma.binstruct.BinStruct):
    MAD_LENGTH = 64
    MEMBERS = [
        ('agent_id', 32, 1),
        ('status', 32, 1),
        ('timeout_ms', 32, 1),
        ('retries', 32, 1),
        ('length', 32, 1),
        ('qpn', 32, 1),
        ('qkey', 32, 1),
        ('lid', 16, 1),
        ('sl', 8, 1),
        ('path_bits', 8, 1),
        ('grh_present', 8, 1),
        ('gid_index', 8, 1),
        ('hop_limit', 8, 1),
        ('traffic_class', 8, 1),
        ('gid', 128, 1),
        ('flow_label', 32, 1),
        ('pkey_index', 16, 1),
        ('reserved_58', 8, 6),
    ]

    def __init__(self, buf=None, offset: int=0):
        rdma.binstruct.BinStruct.__init__(self, buf, offset)
        self.buf = buf[offset: offset + self.MAD_LENGTH]
        assert len(self.buf) == self.MAD_LENGTH

    def unpack_from(self, buffer, offset: int=0):
        from socket import htonl as cpu_to_be32
        from socket import htons as cpu_to_be16

        (
            self.agent_id, self.status, self.timeout_ms, self.retries, self.length,
            self.qpn, self.qkey, self.lid, self.sl, self.path_bits, self.grh_present, self.gid_index,
            self.hop_limit, self.traffic_class, self.gid, self.flow_label, self.pkey_index, self.reserved_58
        ) = struct.unpack_from(
            "=LLLLLLLHBBBBBB16sLH6s", buffer, offset + 0,
        )

        self.qpn = cpu_to_be32(self.qpn)
        self.qkey = cpu_to_be32(self.qkey)
        self.lid = cpu_to_be16(self.lid)
        self.gid = IBA.GID(self.gid, raw=True)
        self.flow_label = cpu_to_be32(self.flow_label)

    def pack_into(self, buffer, offset: int=0):
        assert len(buffer) == self.MAD_LENGTH
        buffer[:] = self.buf


def decode_umad(o, in_bytes):
    """Assume bytes star ts with a umad header and parse accordingly."""
    if o.verbosity >= 1:
        UMADHdr(in_bytes).printer(sys.stdout)
    return in_bytes[UMADHdr.MAD_LENGTH:]


def cmd_decode_mad(argv, o):
    """Accept on stdin a hex dump of a MAD and pretty print it.
       Usage: %prog [-v]

       All spaces and newlines are removed from the input text, the
       result must be a single string of hex digits."""
    import libibtool.vendstruct
    libibtool.vendstruct.install_vend()
    o.add_option(
        "-v",
        "--verbosity",
        dest="verbosity",
        action="count",
        default=0,
        help="Increase the verbosity level of diagnostic messages, each -v increases by 1.",
    )
    o.add_option(
        "-o",
        "--offset",
        dest="offset",
        action="store",
        default=0,
        type=int,
        help="Start at this offest before decoding.",
    )
    o.add_option(
        "-l",
        dest="lrh",
        action="store_true",
        help="The data starts at the LRH, not the MAD header",
    )
    o.add_option(
        "--umad",
        dest="umad",
        action="store_true",
        help="The data includes a kernel umad header, eg it is from /dev/infiniband/umadX",
    )
    args, values = o.parse_args(argv, expected_values=0)
    o.verbosity = args.verbosity

    print("Input the MAD in HEX followed by Ctrl-D")
    inp = "".join(sys.stdin.readlines())
    if inp[0] == '"' or inp[0] == "'":
        in_bytes = inp.strip()[1:-1].decode("string_escape")
    else:
        inp = inp.replace(" ", "").replace("\n", "").replace("\r", "").replace("\t", "")
        if o.verbosity >= 2:
            print("Input HEX value is:\n  ", repr(inp))
        in_bytes = codecs.decode(inp, "hex")
    in_bytes = in_bytes[args.offset:]
    if o.verbosity >= 2:
        print(codecs.encode(in_bytes, "hex"))

    if args.umad:
        in_bytes = decode_umad(o, in_bytes)

    if args.lrh:
        in_bytes = decode_link(o, in_bytes)

    hdr = IBA.MADHeader(in_bytes)
    if o.verbosity >= 1:
        hdr.printer(sys.stdout)
    kind = IBA.get_fmt_payload(*rdma.madtransactor.MADTransactor.get_request_match_key(in_bytes))
    if kind[0] is None:
        if o.verbosity == 0:
            hdr.printer(sys.stdout)
        raise CmdError("Don't know what this mgmtClass/classVersion is.")
    fmt = kind[0](in_bytes)
    print(
        fmt.__class__.__name__,
        fmt.describe(),
    )
    fmt.printer(sys.stdout, header=False)


def cmd_set_nodedesc(argv, o):
    """Set or display the node description for CAs.
       Usage: %prog [-v] [NAME]

       By default all CAs are altered, use -C or -P to select a single CA."""
    o.add_option(
        "-v",
        dest="view_all",
        action="store_true",
        help="Increase the verbosity level of diagnostic messages, each -v increases by 1.",
    )
    o.add_option(
        "-C",
        "--Ca",
        dest="CA",
        help="RDMA device to use. Specify a device name or node GUID",
    )
    o.add_option(
        "-P",
        "--Port",
        dest="port",
        help="RDMA end port to use. Specify a GID, port GUID, DEVICE/PORT or port number.",
    )
    (args, values) = o.parse_args(argv)

    dev = None
    if args.CA is not None:
        dev = rdma.get_device(args.CA)
    if dev is None and args.port is not None:
        dev = rdma.get_end_port(args.port).parent

    if args.view_all or len(values) <= 0:
        for cur_dev in rdma.get_devices():
            if dev is not None and cur_dev != dev:
                continue
            print(
                "{}: {}".format(
                    cur_dev.name,
                    IBA_describe.dstr(cur_dev.node_desc),
                ),
            )
    else:
        name = values[0].decode()
        name = name.encode("utf-8")
        for cur_dev in rdma.get_devices():
            if dev is not None and cur_dev != dev:
                continue
            with open(os.path.join(cur_dev._dir, "node_desc"), "w") as F:
                F.write(name)
    return True
