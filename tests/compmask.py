# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.
# -*- coding: utf-8 -*-


import unittest

import rdma.IBA as IBA


class CompmaskTest(unittest.TestCase):
    def test_mask_sapathrecord(self):
        obj = IBA.SAPathRecord()
        cm = IBA.ComponentMask(obj)

        self.assertEqual(cm.DGID, obj.DGID)
        cm.DGID = IBA.GID("::1")
        self.assertEqual(cm.DGID, obj.DGID)
        self.assertEqual(obj.DGID, IBA.GID("::1"))

        self.assertEqual(cm.component_mask, 4)

        cm.DLID = 1
        self.assertEqual(cm.component_mask, 20)

    def test_mask_portinforecord(self):
        obj = IBA.SAPortInfoRecord()
        cm = IBA.ComponentMask(obj)

        cm.portInfo.capabilityMask = 1

        self.assertEqual(cm.component_mask, 1 << 7)

    def test_mask_linearforwardingtablerecord(self):
        obj = IBA.SALinearForwardingTableRecord()
        cm = IBA.ComponentMask(obj)

        cm.linearForwardingTable.portBlock[0] = 1

        self.assertEqual(cm.component_mask, 1 << 3)


if __name__ == "__main__":
    unittest.main()
