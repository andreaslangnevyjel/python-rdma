# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.
# -*- coding: utf-8 -*-


import unittest

import rdma


class GetUmadTest(unittest.TestCase):
    @staticmethod
    def test_get():
        for dev in rdma.get_devices():
            for port in dev.end_ports:
                with rdma.get_umad(port) as entry:
                    print(entry)


if __name__ == "__main__":
    unittest.main()
