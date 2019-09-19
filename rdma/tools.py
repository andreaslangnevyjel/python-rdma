# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.
# -*- coding: utf-8 -*-

import collections
import io
import os
import os.path
import stat
from typing import Tuple, Union, List

import rdma


def ib_ioc(direction: int, type_: int, nr: int, size: int) -> int:
    """
    Emulate the C _IOC macro
    """
    return (
        (nr << 0) |
        (type_ << (0 + 8)) |  # (_IOC_NRSHIFT+_IOC_NRBITS)
        (size << (0 + 8 + 8)) |  # (_IOC_TYPESHIFT+_IOC_TYPEBITS)
        (direction << (0 + 8 + 8 + 14))  # (_IOC_SIZESHIFT+_IOC_SIZEBITS)
    )


class SysFSDevice(object):
    """
    Handle to a /dev/ char device kernel interface. This supports the
    context manager protocol.
    """
    def __init__(self, parent, sys_dir):
        self.parent = parent
        self.dev, self.dev_fn = self._open_dev_from_sysfs(sys_dir)
        self._sys_dir = sys_dir

    @staticmethod
    def _try_open(path: str, dev) -> Union[Tuple, None]:
        """
        Try to open a device node that should correspond to character
        device dev. Return None if it did not turn out.
        """
        try:
            st = os.lstat(path)
            if not stat.S_ISCHR(st.st_mode) or st.st_rdev != dev:
                return None
            f_obj = io.FileIO(path, "r+")
            st2 = os.fstat(f_obj.fileno())
            if st.st_mode == st2.st_mode and st.st_rdev == st2.st_rdev:
                return f_obj, path
            f_obj.close()
        except OSError:
            pass
        return None

    def _open_dev_from_sysfs(self, sysfs):
        """Given the sysfs path to a device node descriptor find that device
        in /dev/"""
        name = os.path.basename(sysfs)
        try:
            with open(sysfs + "/dev") as f_obj:
                dev = f_obj.read().strip().split(":")
                dev = os.makedev(int(dev[0]), int(dev[1]))
        except IOError:
            raise rdma.RDMAError(
                "Unable to open device node for {}, bad dev file?".format(
                    repr(name),
                ),
            )

        f_obj = self._try_open("/dev/infiniband/{}".format(name), dev)
        if f_obj:
            return f_obj
        f_obj = self._try_open("/dev/{}".format(name), dev)
        if f_obj:
            return f_obj
        for root, dirs, files in os.walk("/dev/"):
            for cur_f in files:
                f_obj = self._try_open("{}/{}".format(root, cur_f), dev)
                if f_obj:
                    return f_obj
        raise rdma.RDMAError(
            "Unable to open device node for {}".format(repr(name)),
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.dev.close()

    def close(self):
        return self.dev.close()


finfo = collections.namedtuple("finfo", "type mask")


def struct(name: str, fields: List):
    """Construct a mutable :class:`collections.namedtuple` with a MASK
    tracking feature."""

    def init(self, **args):
        for k in args:
            if k not in list(self._finfo.keys()):
                raise TypeError(
                    "{}() got an unexpected keyword argument '{}'".format(
                        name,
                        k,
                    ),
                )
        mask = 0
        self.MASK = 0
        for k, f in list(self._finfo.items()):
            if k in args:
                v = args[k]
                mask |= f.mask
            elif callable(f.type):
                v = f.type()
            else:
                v = f.type
            setattr(self, k, v)

        self.MASK = mask

    def sattr(self, k, v):
        if k != "MASK" and k not in list(self._finfo.keys()):
            raise AttributeError(
                "'{}' object has no attribute '{}'".format(
                    name,
                    k,
                ),
            )

        object.__setattr__(self, k, v)
        if k != "MASK":
            f = self._finfo[k]
            object.__setattr__(self, "MASK", self.MASK | f.mask)

    def pretty(self) -> str:
        _result = []
        for key, value in list(self._finfo.items()):
            s = "{}={}".format(key, getattr(self, key))
            if self.MASK & value.mask:
                s += "*"
            _result.append(s)
        return ",".join(_result)

    n_dict = {
        "_finfo": {
            field[0]: finfo(
                field[1],
                field[2] if len(field) > 2 else 0,
            ) for field in fields
        },
        "__init__": init,
        "__setattr__": sattr,
        "__str__": pretty,
    }
    return type(name, (object,), n_dict)
