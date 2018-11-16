# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.
# -*- coding: utf-8 -*-


import os
import sys
import unittest

import rdma.IBA as IBA
import rdma.binstruct

structs = set(I for I in IBA.__dict__.values()
              if isinstance(I, type) and issubclass(I, rdma.binstruct.BinStruct))


class StructsTest(unittest.TestCase):
    def test_component_mask(self):
        # See C15-0.1.27
        self.assertEqual(
            IBA.SAPortInfoRecord.COMPONENT_MASK["portInfo.capabilityMask"],
            7,
        )
        self.assertEqual(
            IBA.SALinearForwardingTableRecord.COMPONENT_MASK["linearForwardingTable.portBlock"],
            3,
        )

    @staticmethod
    def test_odd_size():
        fmt = IBA.SMPFormatDirected()
        dr_path = bytes(b"0" * 65)
        fmt.initialPath[:len(dr_path)] = dr_path
        test = bytearray(fmt.MAD_LENGTH)
        fmt.pack_into(test)
        assert (len(test) == 257)

        fmt2 = IBA.SMPFormatDirected(test)
        fmt.printer(sys.stdout)
        fmt.printer(sys.stdout, format="dotted")
        fmt2.printer(sys.stdout)
        fmt2.printer(sys.stdout, format="dotted")

    def test_struct_packer(self):
        """Checking struct pack and unpack."""
        test = bytearray(512)
        testr = bytes(test)
        for I in structs:
            I().pack_into(test)
            assert (len(test) == 512)
            I().unpack_from(testr)
            I(testr)

        raw = os.urandom(512)
        for I in structs:
            attr = I()
            attr.unpack_from(raw)
            attr.pack_into(test)
            self.assertEqual(raw[0:I.MAD_LENGTH], test[0:I.MAD_LENGTH])

    @staticmethod
    def test_struct_printer_dump():
        """Checking printer dump style"""
        for _struct in structs:
            _struct().printer(sys.stdout)

    @staticmethod
    def test_struct_printer_dotted():
        """Checking printer dotted style"""
        for _struct in structs:
            _struct().printer(sys.stdout, format="dotted")


if __name__ == "__main__":
    unittest.main()
