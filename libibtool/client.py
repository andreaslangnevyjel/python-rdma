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
    t_lid = 121
    ep = None
    for dev in rdma.get_devices():
        for ep in dev.end_ports:
            if ep.state >= IBA.PORT_STATE_INIT:
                break
    umad = rdma.get_umad(ep)
    print("umad for {} is {}".format(str(ep), str(umad)))
    path = get_gmp_path(tmpl_target(str(t_lid), ep, None, None), umad)
    # local_path = get_gmp_path(tmpl_target(str(1), ep, None, None), umad)
    # print(local_path)
    print("{!r}".format(path))
    # sched = rdma.sched.MADSchedule(umad)
    # my_hs = HS(path, sched)
    qpn = 2000
    if True:
        path.dqpn = qpn
        path.qkey = 0
        my_vmad = VMAD(ep, path, depth=16)
        print("s/d/q:", path.sqpn, path.dqpn, path.qkey)
        stat_msg = struct.pack(">xxxBLLLQLL", WCUCmdEnum.stat_req.value, ep.lid, qpn, path.qkey, 0, 0, 0)
        # print(len(stat_msg), stat_msg)
        # print(my_vmad._qp.qp_num)
        my_vmad.sendto(stat_msg, path)
        res = my_vmad.recvfrom(time.monotonic() + 1.0)
        # print(len(res[0]))
        print(struct.unpack(">xxxBLLLQLL", res[0][:32]))

        data_key = qpn + 1
        print("data key is {:d}".format(data_key))
        stat_msg = struct.pack(">xxxBLLLQLL", WCUCmdEnum.data_req.value, ep.lid, qpn, data_key, 0, 0, 0)
        # print(len(stat_msg), stat_msg)
        # print(my_vmad._qp.qp_num)
        print(my_vmad.sendto(stat_msg, path))
        res = my_vmad.recvfrom(time.monotonic() + 1.0)
        # print(len(res[0]))
        data_res = struct.unpack(">xxxBLLLQLL", res[0][:32])
        print(data_res)
        new_dqpn = data_res[3]
        v_addr = data_res[4]
        rkey = data_res[5]
        print("dqpn={:d}, v_addr={:x}, rkey={:d}".format(new_dqpn, v_addr, rkey))
        # return

        print("data ---")
        ctx = rdma.get_verbs(ep)
        with ctx.pd() as pd:
            recv_pd = pd  # ctx.pd()
            print(pd, recv_pd)
            depth = 1
            size = 32 * 1024 * 1024  # * 1024 * 2
            cc = ctx.comp_channel()
            cq = ctx.cq(2 * depth, cc)
            # srq = pd.srq(depth)
            poller = rdma.vtools.CQPoller(cq)
            num_sge = 16
            srq = recv_pd.srq(depth)
            qp = pd.qp(ibv.IBV_QPT_UC, depth, cq, depth, cq, max_send_sge=num_sge, max_recv_sge=1, srq=srq)
            recv_qp = recv_pd.qp(ibv.IBV_QPT_UC, depth, cq, depth, cq, max_send_sge=num_sge, max_recv_sge=1, srq=srq)
            mem = mmap.mmap(-1, size)
            mr = pd.mr(
                mem,
                ibv.IBV_ACCESS_LOCAL_WRITE | ibv.IBV_ACCESS_REMOTE_WRITE,
            )
            recv_path = path.copy().reverse(for_reply=False)
            # recv_path = local_path.copy().reverse(for_reply=False)
            print("data_key=", data_key)
            recv_path.dqpn = data_key
            # recv_path.SL = 1
            path.ServiceID = 0
            recv_path.ServiceID = 1
            # recv_path = path.copy()
            # rdma.path.fill_path(recv_qp, recv_path, max_rd_atomic=0)
            # path.sqpn = qpn
            path.SL = 1
            path.dqpn = new_dqpn
            path.qkey = new_dqpn
            recv_path.qkey = 0
            recv_path.dqpn = data_key
            # rdma.path.fill_path(recv_qp, recv_path, max_rd_atomic=0)
            # print("***", qp.qp_num, new_dqpn)
            # print("s/d/q:", path.sqpn, path.dqpn, path.qkey)
            # my_bp = vtools.BufferPool(pd, 2 * depth, 1024 * 1024)
            # my_bp.post_recvs(qp, min(qp.max_recv_wr, depth))
            print(qp, recv_qp)
            print("SL=", path.SL, recv_path.SL)
            block = size / num_sge + 1
            sg_list = []
            offset = 0
            while offset < size:
                if offset + block > size:
                    block = size - offset
                sg_list.append(mr.sge(block, offset))
                offset += block

            read_buffer = rdma.vtools.BufferPool(recv_pd, 2 * depth, 256 + 40)
            read_buffer.post_recvs(srq, depth)
            print("*** send_path {!r}".format(path.forward_path))
            print("*** recv_path {!r}".format(recv_path.forward_path))
            print(qp.qp_num, recv_qp.qp_num)
            print("i/p", path.pkey_index, path.end_port.port_id)
            print("i/p", recv_path.pkey_index, recv_path.end_port.port_id)
            qp.establish(path.forward_path, ibv.IBV_ACCESS_REMOTE_WRITE)
            recv_qp.establish(recv_path.forward_path, ibv.IBV_ACCESS_REMOTE_WRITE | ibv.IBV_ACCESS_REMOTE_READ)
            # time.sleep(3600)
            swr = ibv.send_wr(
                wr_id=0,
                remote_addr=v_addr + 1000,
                rkey=rkey,
                sg_list=sg_list,
                opcode=ibv.IBV_WR_RDMA_WRITE,
                send_flags=ibv.IBV_SEND_SIGNALED,
            )
            # rr = []
            # for _idx in range(depth):
            #    buf_idx = read_buffer.pop()
            #    r_wr = ibv.recv_wr(
            #        wr_id=buf_idx | read_buffer.RECV_FLAG,
            #        sg_list=mr.sge(buf_idx, 256 + 40),
            #    )
            #    print("rb=", buf_idx, r_wr)
            #    rr.append(r_wr)
            # recv_qp.post_recv(rr)
            iters = 4  # 000000

            tpost = time.monotonic()
            for i in range(depth):
                # print("send", swr, dir(swr))
                qp.post_send(swr)

            completions = 0
            posts = depth
            last_out = time.monotonic()
            # print(dir(recv_qp))
            print("\n*** poller ***\n")
            for wc in poller.iterwc(count=10, timeout=3600.0):
                # print(wc, cq.poll())
                if wc.status != ibv.IBV_WC_SUCCESS:
                    raise ibv.WCError(wc, cq, obj=qp)
                print("loop")
                read_buffer.finish_wcs(srq, wc)
                print(wc.opcode, ibv.IBV_WC_RECV, ibv.IBV_WC_RDMA_WRITE)
                completions += 1
                if posts < iters:
                    cur_time = time.monotonic()
                    if abs(cur_time - last_out) > 1:
                        last_out = cur_time
                        rate = size * completions / (cur_time - tpost)
                        print(
                            "{:5.1f}% {}".format(
                                100 * completions / iters,
                                logging_tools.get_size_str(
                                    rate * 8,
                                    per_second=True,
                                    unit="Bit",
                                    long_format=True,
                                ),
                            ),
                        )
                    qp.post_send(swr)
                    posts += 1
                    print("send")
                    poller.wakeat = time.monotonic() + 1
                if completions == iters:
                    print("done")
                    break
            else:
                raise rdma.RDMAError("CQ timed out")
            tcomp = time.monotonic()

            rate = size * iters / (tcomp - tpost)
            print(logging_tools.get_size_str(rate * 8, per_second=True, unit="Bit", long_format=True))

    if False:
        ctx = rdma.get_verbs(ep)
        with ctx.pd() as pd:
            depth = 16
            cq = ctx.cq(2 * depth)
            srq = pd.srq(depth)
            poller = rdma.vtools.CQPoller(cq)
            qp = pd.qp(ibv.IBV_QPT_UD, depth, cq, depth, cq)
            path.sqpn = qp.qp_num
            path.dqpn = qpn
            path.qkey = 0
            print("***", qp.qp_num)
            print("s/d/q:", path.sqpn, path.dqpn, path.qkey)
            stat_msg = struct.pack("<xxxBLLLQLL", WCUCmdEnum.stat_req.value, ep.lid, qpn, 0, 0, 0, 0)
            my_bp = vtools.BufferPool(pd, 2 * depth, 256 + 40)
            my_bp.post_recvs(qp, min(qp.max_recv_wr, depth))
            qp.establish(path)
            buf_idx = my_bp.pop()
            my_bp.copy_to(stat_msg, buf_idx)
            print(min(qp.max_recv_wr, depth))
            print(buf_idx, stat_msg)
            qp.post_send(
                my_bp.make_send_wr(
                    buf_idx,
                    len(stat_msg),
                    path,
                ),
            )
            # print([x.opcode for x in cq.poll()])
            print("send done", type(poller))
            for wc in poller.iterwc(count=2, timeout=0.5):
                print(wc.opcode)
                if wc.opcode & ibv.IBV_WC_RECV:
                    print("R", wc, wc.byte_len, type(wc))
                if wc.opcode == ibv.IBV_WC_SEND:
                    print("S", wc)
                my_bp.finish_wcs(srq, wc)
            print(dir(my_bp))
            # print(my_bp.copy_from(buf_idx, length=32))
            # print(my_bp.p)


if __name__ == "__main__":
    main()
