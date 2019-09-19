# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.
# -*- coding: utf-8 -*-

import rdma.IBA_describe as IBA_describe
import rdma.discovery
import rdma.satransactor
import rdma.subnet
from libibtool.libibopts import *


def display_mfdb(switch, path, show_all: bool):
    print(
        "Multicast mlids [0x{:x}-0x{:x}] of switch {} {!r}".format(
            IBA.LID_MULTICAST,
            IBA.LID_MULTICAST + len(switch.mfdb) - 1,
            path,
            switch.desc,
        ),
    )
    print(
        "     Ports:",
        " ".join(
            "{:3d}".format(_idx) for _idx in range(switch.ninf.numPorts + 1)
        ),
    )
    print(" MLid")
    count = 0
    for lid, bits in enumerate(switch.mfdb):
        if bits == 0 and not show_all:
            continue

        s = " ".join(
            (" x " if bits & (1 << _idx) else "   ") for _idx in range(switch.ninf.numPorts + 1)
        )
        count = count + 1
        print(
            "0x{:x}       {}".format(
                IBA.LID_MULTICAST + lid,
                s,
            )
        )

    # If a default route is configured then show it as well.
    bits = 0
    if 0 < switch.swinf.defaultMulticastPrimaryPort <= switch.ninf.numPorts:
        bits = bits | (1 << switch.swinf.defaultMulticastPrimaryPort)
        if 0 < switch.swinf.defaultMulticastNotPrimaryPort <= switch.ninf.numPorts:
            bits = bits | (1 << switch.swinf.defaultMulticastNotPrimaryPort)
    if bits != 0:
        print(
            "default      {}".format(
                " ".join(
                    (" x " if bits & (1 << _idx) else "   ") for _idx in range(switch.ninf.numPorts + 1)
                ),
            ),
        )

    if show_all:
        print("{:d} mlids dumped".format(count))
    else:
        print("{:d} valid mlids dumped".format(count))


def display_lfdb(switch, sbn, path, show_all):
    max_port = switch.ninf.numPorts
    print(
        "Unicast lids [{:d}-{:d}] of switch {} {!r}".format(
            0,
            len(switch.lfdb) - 1,
            path,
            switch.desc,
        ),
    )
    print("  Lid  Out   Destination")
    print("       Port     Info")
    top_lid = len(sbn.lids)
    count = 0
    for lid, oport in enumerate(switch.lfdb):
        desc = ''
        if oport <= max_port:
            if lid < top_lid:
                port = sbn.lids[lid]
                if port is not None and port.parent is not None:
                    desc = "({} portguid {} {!r})".format(
                        IBA_describe.node_type(port.parent.ninf.nodeType),
                        port.portGUID,
                        port.parent.desc,
                    )
        else:
            if not show_all:
                continue
            if lid == IBA.LID_RESERVED:
                desc = "(reserved LID - illegal port)"
            else:
                desc = "(illegal port)"

        count = count + 1
        print("{:6d} {:03d} : {}".format(lid, oport, desc))
    if show_all:
        print("{:d} lids dumped".format(count))
    else:
        print("{:d} valid lids dumped".format(count))


def get_switch(sched, sbn, args, path):
    node, port = yield rdma.discovery.subnet_ninf_SMP(sched, sbn, path)
    ninf = node.ninf

    if not isinstance(node, rdma.subnet.Switch):
        if args.verbosity >= 1:
            ninf.printer(sys.stdout)
        raise CmdError("Not a switch at {!r}".format(path))

    if node.swinf is None:
        yield node.get_switch_inf(sched, path)
    sched.mqueue(node.get_switch_fdb(sched, args.do_lfdb, args.do_mfdb, path))


def get_top_switch(sched, sbn, args, path):
    yield get_switch(sched, sbn, args, path)
    if isinstance(sched, rdma.satransactor.SATransactor) and not args.no_dests:
        yield rdma.discovery.subnet_ninf_SA(sched, sbn)


def cmd_ibroute(argv, o):
    """
    Display switch forwarding tables.
    Usage: %prog TARGET
    """
    # FIXME: [START_LID [END_LID]]"""
    o.add_option(
        "-a",
        "--all",
        action="store_true",
        dest="all",
        help="Display all ports",
    )
    o.add_option(
        "-n",
        "--no_dests",
        action="store_true",
        dest="no_dests",
        help="Do not try to get information about what the destination LID is.",
    )
    o.add_option(
        "-M",
        "--Multicast",
        action="store_true",
        dest="multicast",
        help="Display the multicast forwarding table.",
    )
    LibIBOpts.setup(o, discovery=True)
    (args, values) = o.parse_args(argv, expected_values=1)
    lib = LibIBOpts(o, args, values, 3, (tmpl_target, tmpl_int, tmpl_int))

    if args.multicast:
        args.do_lfdb = False
        args.do_mfdb = True
        args.no_dests = True
    else:
        args.do_lfdb = True
        args.do_mfdb = False

    # FIXME: Handle start_lid/end_lid

    with lib.get_umad_for_target(values[0]) as umad:
        sched = lib.get_sched(umad, lib.path)
        sbn = lib.get_subnet(sched)

        # FIXME: Better handle a possible cache sbn
        sched.run(mqueue=get_top_switch(sched, sbn, args, lib.path))

        switch = sbn.search_end_port(path=lib.path).parent

        if not args.no_dests:
            if not isinstance(sched, rdma.satransactor.SATransactor):
                max_port = switch.ninf.numPorts
                lid_list = [
                    lid for lid, port in enumerate(switch.lfdb) if port <= max_port and lid != 0
                ]

                sched.run(
                    queue=rdma.discovery.subnet_ninf_LIDS_SMP(
                        sched,
                        sbn,
                        lid_list,
                        True,
                    ),
                )
            else:
                rdma.discovery.load(
                    sched,
                    sbn,
                    [
                        "all_LIDs",
                        "all_NodeDescription",
                        "all_NodeInfo",
                    ],
                )

        sbn.paths = {switch.ports[0]: lib.path}
        switch.trim_db()
        if args.do_mfdb:
            display_mfdb(switch, lib.path, args.all)
        if args.do_lfdb:
            display_lfdb(switch, sbn, lib.path, args.all)
    return lib.done()


def get_switch_incr(sched, sbn, switch, args):
    path = sbn.get_path_smp(sched, switch.ports[0])
    yield sched.mqueue(switch.get_switch_fdb(sched, args.do_lfdb, args.do_mfdb, path))
    switch.path = path
    if args.do_mfdb:
        display_mfdb(switch, path, args.all)
        switch.mfdb = None
    if args.do_lfdb:
        display_lfdb(switch, sbn, path, args.all)
        switch.lfdb = None


def cmd_dump_lfts(argv, o):
    """Display switch forwarding tables from all switches.
       Usage: %prog"""
    LibIBOpts.setup(o, address=False, discovery=True)
    o.add_option(
        "-a",
        "--all",
        action="store_true",
        dest="all",
        help="Display all ports",
    )
    o.add_option(
        "-D",
        action="store_const",
        dest="discovery",
        const="DR",
        help="Perform discovery using directed routing.",
    )
    args, values = o.parse_args(argv, expected_values=0)
    lib = LibIBOpts(o, args, values)

    args.do_lfdb = True
    args.do_mfdb = False

    with lib.get_umad() as umad:
        sched = lib.get_sched(umad)
        sbn = lib.get_subnet(
            sched,
            [
                "all_LIDs",
                "all_NodeDescription",
                "all_SwitchInfo",
            ],
        )
        sched.run(
            mqueue=(
                get_switch_incr(sched, sbn, cur_sw, args) for cur_sw in sbn.iterswitches()
            ),
        )
    return lib.done()


def cmd_dump_mfts(argv, o):
    """Display switch multicast forwarding tables from all switches.
       Usage: %prog"""
    LibIBOpts.setup(o, address=False, discovery=True)
    o.add_option(
        "-a",
        "--all",
        action="store_true",
        dest="all",
        help="Display all ports",
    )
    o.add_option(
        "-D",
        action="store_true",
        dest="direct",
        help="Perform discovery using directed routing.",
    )
    args, values = o.parse_args(argv, expected_values=0)
    lib = LibIBOpts(o, args, values)

    args.do_lfdb = False
    args.do_mfdb = True
    args.no_dests = True

    with lib.get_umad() as umad:
        sched = lib.get_sched(umad)
        sbn = lib.get_subnet(
            sched,
            [
                "all_SwitchInfo",
            ],
        )
        sched.run(
            mqueue=(
                get_switch_incr(sched, sbn, cur_sw, args) for cur_sw in sbn.iterswitches()
            ),
        )
    return lib.done()


def cmd_ibfindnodesusing(argv, o):
    """
    Display the LFT forwarding tables relative to a single link.
    Usage: %prog TARGET PORT

    Use -v to display GUID and LID information for the routed end ports.
    """
    LibIBOpts.setup(o, address=True, discovery=True)
    o.add_option(
        "-a",
        "--all",
        action="store_true",
        dest="all_nodes",
        help="Display all routed end ports, not just CAs",
    )
    args, values = o.parse_args(argv, expected_values=2)
    lib = LibIBOpts(o, args, values, 2, (tmpl_target, tmpl_int))

    args.do_mfdb = False
    args.do_lfdb = True

    args.port = values[1]

    def display_nodes(val):
        ports = set()
        for cv in val:
            l_port = sbn.lids[cv]
            if l_port is not None and (
                args.all_nodes is False or isinstance(l_port.parent, rdma.subnet.CA)
            ):
                ports.add(l_port)

        ports = list(ports)
        ports.sort(key=lambda x: x.parent.desc)

        if o.verbosity >= 1:
            for l_port in ports:
                print(
                    ' {} lid {:d} "{}"'.format(
                        l_port.portGUID,
                        l_port.LID,
                        IBA_describe.dstr(l_port.parent.desc),
                    ),
                )
        else:
            for l_port in ports:
                print(' {}'.format(IBA_describe.dstr(l_port.parent.desc)))

    with lib.get_umad_for_target(values[0]) as umad:
        path = lib.path
        sched = lib.get_sched(umad, path)
        sbn = lib.get_subnet(sched)
        if isinstance(path, rdma.path.IBDRPath):
            sbn.lid_routed = False
            sbn.paths = {}

        sched.run(queue=get_switch(sched, sbn, args, path))
        switch = sbn.path_to_port(path=path).parent
        if args.port <= 0 or args.port > switch.ninf.numPorts:
            raise CmdError(
                "Port {:d} is invalid, switch has {:d} ports".format(
                    args.port,
                    switch.ninf.numPorts,
                ),
            )
        print(switch.desc)
        port = switch.get_port(args.port)
        eport = port.to_end_port()
        lid_list = set(lid for lid, port in enumerate(switch.lfdb) if port == args.port)

        sched.run(queue=rdma.discovery.topo_peer_SMP(sched, sbn, port))
        pport = sbn.topology.get(port)
        if pport is None:
            raise CmdError("No link on port {:d}".format(args.port))
        peport = pport.to_end_port()
        pnode = pport.parent
        if isinstance(pnode, rdma.subnet.Switch):
            ppath = sbn.get_path_smp(sched, pport.to_end_port())
            sched.run(queue=pnode.get_switch_inf(sched, ppath))
            sched.run(queue=pnode.get_switch_fdb(sched, True, False, ppath))
            pport_idx = pnode.ports.index(pport)
            lid_list.update(
                lid for lid, port in enumerate(pnode.lfdb) if port == pport_idx
            )

        sched.run(
            queue=rdma.discovery.subnet_ninf_LIDS_SMP(
                sched,
                sbn,
                list(lid_list),
                True,
            ),
        )
        print(
            '{} {:d} "{}" ==>> {} {:d} "{}"'.format(
                eport.portGUID,
                switch.ports.index(port),
                IBA_describe.dstr(switch.desc),
                peport.portGUID,
                pnode.ports.index(pport),
                IBA_describe.dstr(pnode.desc),
            ),
        )
        display_nodes(LID for LID, port in enumerate(switch.lfdb) if port == args.port)

        print()
        print(
            '{} {:d} "{}" <<== {} {:d} "{}"'.format(
                eport.portGUID,
                switch.ports.index(port),
                IBA_describe.dstr(switch.desc),
                peport.portGUID,
                pnode.ports.index(pport),
                IBA_describe.dstr(pnode.desc),
            ),
        )
        if not isinstance(pnode, rdma.subnet.Switch):
            print(" ** Not a switch **")
        else:
            display_nodes(LID for LID, port in enumerate(pnode.lfdb) if port == pport_idx)

    return lib.done()
