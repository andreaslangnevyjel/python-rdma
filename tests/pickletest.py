# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.
# -*- coding: utf-8 -*-


import pickle as pickle
import unittest

import rdma.IBA as IBA
import rdma.binstruct
import rdma.subnet


class PickleTest(unittest.TestCase):
    def test_basic(self):
        """
        Check that all IBA structs can be pickled and unpickled
        """
        for _val in IBA.__dict__.values():
            if not isinstance(_val, rdma.binstruct.BinStruct):
                continue
            tmp = _val()
            ret = pickle.dumps(_val())
            tmp2 = pickle.loads(ret)
            self.assertEqual(tmp.__class__, tmp2.__class__)

    def test_subnet(self):
        """
        Pickling Subnet objects
        """
        sbn = rdma.subnet.Subnet()

        pinf = IBA.SMPPortInfo()
        for idx in range(1, 100):
            pinf.LID = idx
            port = sbn.get_port_pinf(pinf, port_idx=0, lid=idx)
            port.portGUID = IBA.GUID(0xDEADBEEF0000 | idx)
            sbn.ports[port.portGUID] = port

        ret = pickle.dumps(sbn)
        tmp2 = pickle.loads(ret)

        self.assertEqual(len(sbn.all_nodes), len(tmp2.all_nodes))
        self.assertEqual(sorted(sbn.nodes.keys()), sorted(tmp2.nodes.keys()))
        self.assertEqual(sorted(sbn.ports.keys()), sorted(tmp2.ports.keys()))


if __name__ == '__main__':
    unittest.main()
