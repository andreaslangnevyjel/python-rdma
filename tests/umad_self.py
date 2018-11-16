# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.
# -*- coding: utf-8 -*-


import sys
import unittest

import rdma
import rdma.IBA as IBA
import rdma.path


class UmadSelfTest(unittest.TestCase):
    umad = None

    def setUp(self):
        self.end_port = rdma.get_end_port()
        self.umad = rdma.get_umad(self.end_port)
        self.local_path = rdma.path.IBDRPath(self.end_port)

    def tearDown(self):
        self.umad.close()
        self.umad = None

    def test_node_info(self):
        inf = self.umad.subn_get(IBA.SMPNodeInfo(), self.local_path)
        inf.printer(sys.stdout)
        ports = inf.numPorts

        inf = self.umad.subn_get(IBA.SMPPortInfo, self.local_path)
        inf.printer(sys.stdout)

        self.assertEqual(ports, len(self.end_port.parent.end_ports))
        for I in range(1, ports):
            _inf = self.umad.subn_get(IBA.SMPPortInfo, self.local_path, I)

        self.assertRaises(rdma.MADError,
                          self.umad.subn_get, IBA.SMPPortInfo,
                          self.local_path, ports + 3)

    def test_timeout(self):
        self.assertEqual(self.umad.recvfrom(100), None)


if __name__ == "__main__":
    unittest.main()
