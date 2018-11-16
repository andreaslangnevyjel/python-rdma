# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.
# -*- coding: utf-8 -*-

import sys
import unittest
from contextlib import contextmanager

import rdma
import rdma.IBA as IBA
import rdma.path
import rdma.sched


class MadscheduleTest(unittest.TestCase):
    umad = None
    tid = 0

    def setUp(self):
        self.end_port = rdma.get_end_port()
        self.umad = rdma.get_umad(self.end_port)
        self.local_path = rdma.path.IBDRPath(self.end_port)

    def tearDown(self):
        self.umad.close()
        self.umad = None

    @contextmanager
    def with_assertRaises(self, exc_class):
        """Emulate the python 2.7 assertRaises"""
        try:
            yield
        except exc_class:
            return
        else:
            if hasattr(exc_class, "__name__"):
                exc_name = exc_class.__name__
            else:
                exc_name = str(exc_class)
            raise self.failureException(
                "{} not raised".format(exc_name),
            )

    def test_except(self):
        """
        Check that exceptions flow up the coroutine call chain.
        """

        def second(l_self):
            l_self.count = l_self.count + 1
            raise rdma.RDMAError("moo")

        def first(l_self):
            try:
                yield second(l_self)
            except rdma.RDMAError:
                l_self.count = l_self.count + 1
                raise

        self.count = 0
        sched = rdma.sched.MADSchedule(self.umad)
        with self.with_assertRaises(rdma.RDMAError):
            sched.run(first(self))
        self.assertEqual(self.count, 2)

    def test_except_mad(self):
        """Check that exceptions flow from the MAD decoder."""

        def first(l_self, l_sched):
            inf = yield l_sched.subn_get(IBA.SMPNodeInfo, l_self.local_path)
            with l_self.with_assertRaises(rdma.MADError):
                yield l_sched.subn_get(
                    IBA.SMPPortInfo,
                    l_self.local_path,
                    inf.numPorts + 3,
                )

        sched = rdma.sched.MADSchedule(self.umad)
        sched.run(first(self, sched))

    def get_port_info(self, sched, path, port, follow):
        print(
            "Get port_info {:d} follow={!r}".format(
                port,
                follow,
            )
        )
        pinf = yield sched.subn_get(IBA.SMPPortInfo, path, port)
        print("Done port", port)
        # pinf.printer(sys.stdout)

        if follow and pinf.portState != IBA.PORT_STATE_DOWN:
            npath = rdma.path.IBDRPath(self.end_port)
            npath.drPath = path.drPath + chr(port).encode("ascii")
            print("Probe port", port, repr(npath.drPath))
            yield self.get_node_info(sched, npath)

    def get_node_info(self, sched, path):
        ninf = yield sched.subn_get(IBA.SMPNodeInfo, path)
        if ninf.nodeGUID in self.guids:
            return
        self.guids.add(ninf.nodeGUID)

        print("Got Node {!r}".format(ninf.nodeGUID))
        if ninf.nodeType == IBA.NODE_SWITCH:
            sched.mqueue(
                self.get_port_info(sched, path, _idx, True) for _idx in range(1, ninf.numPorts + 1)
            )
            _pinf = yield sched.subn_get(IBA.SMPPortInfo, path, 0)
        else:
            yield self.get_port_info(
                sched,
                path,
                ninf.local_port_num,
                len(path.drPath) == 1,
            )

    def test_sched(self):
        """Do a simple directed route discovery of the subnet"""
        self.guids = set()
        sched = rdma.sched.MADSchedule(self.umad)
        try:
            sched.run(self.get_node_info(sched, self.local_path))
        except rdma.MADError as err:
            print(err)
            err.req.printer(sys.stdout)
            raise


if __name__ == "__main__":
    unittest.main()
