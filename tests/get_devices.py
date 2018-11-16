# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.
# -*- coding: utf-8 -*-

import unittest

import rdma


class GetDevicesTest(unittest.TestCase):
    @staticmethod
    def test_list():
        devs = rdma.get_devices()
        print(devs)
        for dev in devs:
            print("RDMA Device '{}'".format(dev.name))
            for _name in [
                "node_type",
                "fw_ver",
                "node_guid",
                "node_desc",
                "sys_image_guid",
                "board_id",
                "hw_ver",
            ]:
                print(
                    "    {}: {}".format(
                        _name,
                        repr(getattr(dev, _name)),
                    ),
                )
            for _port in dev.end_ports:
                print("    port: {:d}".format(_port.port_id))
                for _name in [
                    "lid",
                    "lmc",
                    "phys_state",
                    "state",
                    "sm_lid",
                    "sm_sl",
                    "gids",
                    "pkeys",
                ]:
                    print(
                        "        {}: {}".format(
                            _name,
                            repr(getattr(_port, _name)),
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
