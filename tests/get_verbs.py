# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.
# -*- coding: utf-8 -*-

import unittest

import rdma


class GetVerbsTest(unittest.TestCase):
    @staticmethod
    def test_get():
        for dev in rdma.get_devices():
            with rdma.get_verbs(dev) as verb:
                print(verb)
            for port in dev.end_ports:
                with rdma.get_verbs(port) as verb:
                    print(verb)


if __name__ == "__main__":
    unittest.main()
