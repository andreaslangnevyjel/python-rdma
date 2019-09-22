#!/usr/bin/python3-mwct -Otu
# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.
# -*- coding: utf-8 -*-


from typing import Tuple

import rdma.ibverbs as ibv

import rdma
import rdma.path
import rdma.satransactor
import rdma.vmad
from rdma import IBA


class SimpleTest(object):
    umad = None
    tid = 0

    def __init__(self):
        for dev in rdma.get_devices():
            for ep in dev.end_ports:
                if ep.state >= IBA.PORT_STATE_INIT:
                    self.end_port = ep
        self.ctx = rdma.get_verbs(self.end_port)

    def __del__(self):
        self.ctx.close()
        self.ctx = None

    def _get_loop(self, pd, qp_type, depth: int=16) -> Tuple:
        cc = self.ctx.comp_channel()
        cq = self.ctx.cq(2 * depth, cc)
        poller = rdma.vtools.CQPoller(cq)
        srq = pd.srq(depth)
        pool = rdma.vtools.BufferPool(pd, 2 * depth, 256 + 40)
        pool.post_recvs(srq, depth)
        path_a = rdma.path.IBPath(
            self.end_port,
            qkey=999,
            DGID=self.end_port.default_gid,
        )
        # with rdma.get_gmp_mad(self.end_port, verbs=self.ctx) as vmad:
        #    rdma.path.resolve_path(vmad, path_a)
        with rdma.get_umad(self.end_port) as umad:
            rdma.path.resolve_path(umad, path_a, reversible=True)
        qp_a = pd.qp(qp_type, depth, cq, depth, cq, srq=srq)
        rdma.path.fill_path(qp_a, path_a, max_rd_atomic=0)

        qp_b = pd.qp(qp_type, depth, cq, depth, cq, srq=srq)
        path_b = path_a.copy().reverse(for_reply=False)
        rdma.path.fill_path(qp_b, path_b, max_rd_atomic=0)
        qp_b.establish(path_b)
        # print "Path B is",repr(path_b)

        path_a = path_b.copy().reverse(for_reply=False)
        qp_a.establish(path_a)
        # print "Path A is",repr(path_a)

        return path_a, qp_a, path_b, qp_b, poller, srq, pool

    def _do_loop_test(self, qp_type_name):
        """Test HCA loop back between two QPs as well as SRQ."""
        qp_type = getattr(ibv, "IBV_QPT_{}".format(qp_type_name))
        print(
            "Testing QP to QP loop type {:d} {}".format(
                qp_type,
                qp_type_name,
            ),
        )
        with self.ctx.pd() as pd:
            path_a, qp_a, path_b, qp_b, poller, srq, pool = self._get_loop(pd, qp_type)
            print("{!r}".format(path_a))
            print("{!r}".format(path_b))
            qp_b.post_send(pool.make_send_wr(pool.pop(), 256, path_b))
            qp_a.post_send(pool.make_send_wr(pool.pop(), 256, path_a))

            recvs = 0
            sends = 0
            for wc in poller.iterwc(count=4, timeout=0.5):
                if wc.opcode & ibv.IBV_WC_RECV:
                    recvs = recvs + 1
                    print("recv")
                if wc.opcode == ibv.IBV_WC_SEND:
                    sends = sends + 1
                    print("send")
                pool.finish_wcs(srq, wc)
            # self.assertFalse(poller.timedout)
            # self.assertEqual(recvs, 2)
            # self.assertEqual(sends, 2)

    def test_rc_loop(self):
        self._do_loop_test("RC")

    def test_uc_loop(self):
        self._do_loop_test("UC")

    def test_ud_loop(self):
        self._do_loop_test("UD")


if __name__ == "__main__":
    my_test = SimpleTest()
    my_test.test_rc_loop()
    my_test.test_uc_loop()
    my_test.test_ud_loop()
