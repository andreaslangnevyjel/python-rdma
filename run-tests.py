#!/usr/bin/python3-mwct
# -*- coding: utf-8 -*-
# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.

import fnmatch
import os.path
import unittest


def test_all():
    """
    Return a test suite for everything in the test/ directory.
    Replace me with discover for Python 2.7
    """
    return suite


module = __import__("tests")

fns = [
    os.path.splitext(entry)[0] for entry in fnmatch.filter(os.listdir(module.__path__[0]), "*.py")
]
fns.remove("__init__")

for entry in fns:
    __import__("tests." + entry)

suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromNames(fns, module))

if __name__ == "__main__":
    unittest.main(defaultTest="testAll")
