#!/usr/bin/python3-mwct -Otu
# -*- coding: utf-8 -*-

import mmap
import struct
import time
from enum import IntEnum

import rdma.ibverbs as ibv
from mwct.tools import logging_tools

import rdma
import rdma.sched
from libibtool.libibopts import tmpl_target
from rdma import IBA
from rdma import vtools
from rdma.vmad import VMAD


class WCUCmdEnum(IntEnum):
    stat_req = 0
    stat_res = 1
    stat_term = 2
    stat_down = 3
    data_req = 4
    data_res = 5
    data_term = 6
    data_down = 7
    meta_req = 8
    meta_res = 9
    meta_term = 10
    meta_down = 11


def get_gmp_path(path, umad):
    """Return a :class:`rdma.path.IBPath` for *path. The path is suitable
    for use with SMPs."""
    if path.dqpn is None:
        path.dqpn = 1
    if path.qkey is None:
        path.qkey = IBA.IB_DEFAULT_QP1_QKEY
    path = rdma.path.resolve_path(umad, path, reversible=True)
    return path


def main():
    t_lid = 1
    ep = None
    for dev in rdma.get_devices():
        for ep in dev.end_ports:
            if ep.state >= IBA.PORT_STATE_INIT:
                break
    umad = rdma.get_umad(ep)
    print("umad for {} is {}".format(str(ep), str(umad)))
    path = get_gmp_path(tmpl_target(str(t_lid), ep, None, None), umad)
    print("{!r}".format(path))
    # sched = rdma.sched.MADSchedule(umad)
    # my_hs = HS(path, sched)
    qpn = 2001
    if True:
        path.dqpn = qpn
        path.qkey = 0
        data_key = 2001
        print("data ---")
        ctx = rdma.get_verbs(ep)
        with ctx.pd() as pd:
            depth = 1
            size = 32 * 1024 * 1024  # * 1024 * 2
            cc = ctx.comp_channel()
            cq = ctx.cq(2 * depth, cc)
            poller = rdma.vtools.CQPoller(cq)
            srq = pd.srq(depth)
            qp = pd.qp(ibv.IBV_QPT_UC, depth, cq, depth, cq, srq=srq)
            print("data_key=", data_key)
            # path.ServiceID = 0
            # path.SL = 1
            path.sqpn = 1

            write_buffer = rdma.vtools.BufferPool(pd, 2 * depth, 256 + 40)
            write_buffer.post_recvs(srq, depth)
            print("*** send_path {!r}".format(path.forward_path))
            qp.establish(path.forward_path, ibv.IBV_ACCESS_REMOTE_WRITE)
            print("* send")
            qp.post_send(write_buffer.make_send_wr(write_buffer.pop(), 16, path))

            # print(dir(recv_qp))
            print("\n*** poller ***\n")
            for wc in poller.iterwc(count=10, timeout=2.0):
                # print(wc, cq.poll())
                if wc.status != ibv.IBV_WC_SUCCESS:
                    raise ibv.WCError(wc, cq, obj=qp)
                print("loop")
                print(wc)
                write_buffer.finish_wcs(srq, wc)
                break
            else:
                raise rdma.RDMAError("CQ timed out")


if __name__ == "__main__":
    main()
