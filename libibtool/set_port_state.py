# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.
# -*- coding: utf-8 -*-


import copy

import rdma.discovery
import rdma.madtransactor
import rdma.subnet
from libibtool.libibopts import *


def cmd_init_all_ports(argv, o):
    """
    Set the port state value to INIT for all links.
    Usage: %prog

    This can be used to try and recover a subnet that has deadlock or other
    fabric issues by dropping all the links back to INIT and thus blocking
    non-management traffic. It may need to be run multiple times before
    it completes.
    """
    LibIBOpts.setup(o)
    args, values = o.parse_args(argv, expected_values=0)
    lib = LibIBOpts(o, args, values)

    with lib.get_umad_for_target(False) as umad:
        sched = lib.get_sched(umad, lib.path)

        # We borrow the internal topology scanner to make this go
        # appropriately.
        class MyTopo(rdma.discovery._SubnetTopo):
            def do_port(self, path, node, aport, port_idx, depth):
                yield rdma.discovery._SubnetTopo.do_port(
                    self,
                    path,
                    node,
                    aport,
                    port_idx,
                    depth,
                )
                try:
                    pinf = copy.copy(aport.pinf)
                    if (
                        pinf is None or port_idx == 0 or
                        pinf.portState == IBA.PORT_STATE_DOWN or
                        pinf.portState == IBA.PORT_STATE_INIT
                    ):
                        return
                    pinf.portPhysicalState = 0
                    pinf.linkSpeedEnabled = 0
                    pinf.linkWidthEnabled = 0
                    pinf.portState = IBA.PORT_STATE_DOWN
                    yield self.sched.subn_set(pinf, path, port_idx)
                except rdma.MADError as e:
                    print(
                        "Failed to set port state on {} via {}".format(
                            aport,
                            path,
                        ),
                    )
                    print("   ", e)

        sbn = rdma.subnet.Subnet()
        fetcher = MyTopo(sched, sbn, get_desc=False, lid_route=False)
        path = rdma.path.IBDRPath(sched.end_port, retries=10)
        sched.run(queue=(fetcher.do_node(path),))
    return lib.done()


def cmd_set_port_state(argv, o):
    """Set the port state value for multiple end ports.
       Usage: %prog [TARGET@PORT_NUM]+

       This intelligently selects a DR path to disable/enable links in the
       network. For instance if this command is used to create a partition in
       the network then it will find DR paths that do not cross the partition
       and ensure that the arguments are all on this side of the partition.

       Use --disable to turn the ports off, --enable to turn them back on, or
       --init to reset ports back to INIT."""
    o.add_option(
        "--disable",
        dest="phys_state",
        action="store_const",
        default=0,
        const=IBA.PHYS_PORT_STATE_DISABLED,
        help="Set the physical port state to disabled.",
    )
    o.add_option(
        "--enable",
        dest="phys_state",
        action="store_const",
        default=0,
        const=IBA.PHYS_PORT_STATE_POLLING,
        help="Set the physical port state to polling.",
    )
    o.add_option(
        "--init",
        dest="port_state",
        action="store_const",
        default=0,
        const=IBA.PORT_STATE_INIT,
        help="Set the port state to initialize.",
    )
    LibIBOpts.setup(o, address=True, discovery=True)
    (args, values) = o.parse_args(argv)

    # Strip off the @ index
    nvalues = []
    port_idxs = []
    for I in range(len(values)):
        s = values[I].partition('@')
        nvalues.append(s[0])
        if s[2] == '':
            port_idxs.append(None)
        else:
            port_idxs.append(int(s[2]))
    values = nvalues

    tmpl = tuple(tmpl_target for _idx in values)
    lib = LibIBOpts(o, args, values, min(1, len(tmpl)), tmpl)

    with lib.get_umad_for_target(False) as umad:
        sched = lib.get_sched(umad, lib.path)
        sbn = lib.get_subnet(
            sched,
            [
                "all_NodeInfo",
                "all_PortInfo",
                "all_topology",
            ],
        )

        otopology = copy.copy(sbn.topology)
        eps = []
        for I in range(len(values)):
            path = values[I]
            # path_to_port can resolve the possible command line arguments, so
            # we do not need to use path.resolve_path.
            port = sbn.path_to_port(path)
            if port is None:
                raise CmdError(
                    "Could not find path {} in the subnet".format(
                        path,
                    ),
                )
            eps.append(port)
            port_idx = port_idxs[I]
            if port_idx is None:
                if not isinstance(port.parent, rdma.subnet.Switch):
                    port_idxs[I] = port_idx = port.port_id
                else:
                    raise CmdError(
                        "Need to have a port index for switch {}".format(
                            port.portGUID,
                        ),
                    )

            # Remove the links we are going to affect from the topology
            port = port.parent.get_port(port_idx)
            peer = sbn.topology.get(port)
            try:
                del sbn.topology[path]
            except KeyError:
                pass
            try:
                del sbn.topology[peer]
            except KeyError:
                pass

        def get_path(ep, l_port_idx):
            try:
                return dr.get_path(ep)
            except ValueError:
                pass

            # Hmm, the user picked the wrong port somehow, try to help the
            # user.
            l_peer = otopology.get(ep.parent.get_port(l_port_idx))
            try:
                dr.get_path(l_peer.to_end_port())
            except ValueError:
                raise CmdError(
                    "No DR path exists to {} port {:d}".format(
                        ep.portGUID,
                        l_port_idx,
                    ),
                )
            raise CmdError(
                "No DR path exists to {} port {:d} - try using the peer {} port {:d}".format(
                    ep.portGUID,
                    l_port_idx,
                    l_peer.to_end_port().portGUID,
                    l_peer.port_id,
                ),
            )

        dr = sbn.get_dr_cache(umad.parent)
        dpath = [get_path(port, port_idx) for port, port_idx in zip(eps, port_idxs)]

        pinfs = [umad.subn_get(IBA.SMPPortInfo, path, port_idx)
                 for path, port_idx in zip(dpath, port_idxs)]

        # Do all the sets at once, at the end.
        for pinf, path, port_idx, port in zip(pinfs, dpath, port_idxs, eps):
            # NOP the modification pinf.
            mpinf = copy.copy(pinf)
            mpinf.portState = args.port_state
            mpinf.portPhysicalState = args.phys_state
            mpinf.linkSpeedEnabled = 0
            mpinf.linkWidthEnabled = 0

            if args.phys_state != 0:
                umad.subn_set(mpinf, path, port_idx)
            else:
                print(
                    "Would have changed {}@{:d} on {}".format(
                        port.portGUID,
                        port_idx,
                        path,
                    ),
                )
    return lib.done()
