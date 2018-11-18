#!/usr/bin/python3-mwct
# -*- coding: utf-8 -*-
# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.

import importlib.machinery
import os.path
import re
import sys
from distutils import log
from distutils.core import Command
from distutils.core import setup
from distutils.extension import Extension

import Cython.Compiler.Version
import Cython.Distutils


class BuildExt(Cython.Distutils.build_ext):
    def build_extensions(self):
        self.codegen()
        Cython.Distutils.build_ext.build_extensions(self)

    @staticmethod
    def get_enums(f_obj):
        ret_f = []
        skip = True
        for line in f_obj.readlines():
            if line[0] == "#":
                skip = line.find("infiniband/verbs.h") == -1
            else:
                if not skip:
                    ret_f.append(line)
        ret_s = "".join(ret_f)

        enum = {}
        for m in re.finditer(r"enum\s+(\w+)\s*{(.*?)}", ret_s, re.DOTALL):
            name = m.group(1)
            constants = [
                c.partition("=")[0].strip() for c in m.group(2).split(",") if c.strip() != ""
            ]
            enum[name] = tuple(constants)

        return enum

    @staticmethod
    def write_enums_pxd(f_obj, enums):
        print(
            "\n\n".join(
                "\n".join(
                    "%s = c.%s" % (c, c) for c in v
                ) for e, v in sorted(enums.items())
            ),
            file=f_obj,
        )

    @staticmethod
    def write_enums_pxi(f_obj, enums):
        sep = "\n" + " " * 8
        print(
            "\n\n".join(
                "    enum {}:{}".format(
                    e,
                    sep,
                ) + sep.join(v) for e, v in sorted(enums.items())
            ),
            file=f_obj,
        )

    def codegen(self):
        if not os.path.exists(self.build_temp):
            os.makedirs(self.build_temp)
        verbs_h = os.path.join(self.build_temp, "verbs_h.c")
        verbs_h_o = verbs_h + ".out"
        with open(verbs_h, "wt") as f_obj:
            f_obj.write("#include <infiniband/verbs.h>")
        self.compiler.preprocess(verbs_h, verbs_h_o)

        with open(verbs_h_o) as f_obj:
            enums = self.get_enums(f_obj)
        with open("rdma/libibverbs_enums.pxd", "wt") as f_obj:
            print("cdef extern from 'infiniband/verbs.h':", file=f_obj)
            self.write_enums_pxi(f_obj, enums)
        with open("rdma/libibverbs_enums.pxi", "wt") as f_obj:
            self.write_enums_pxd(f_obj, enums)


ibverbs_module = Extension(
    "rdma.ibverbs",
    ["rdma/ibverbs.pyx"],
    libraries=[":libibverbs.so.1"],
    library_dirs=["/usr/lib64"],
    depends=[
        "rdma/libibverbs.pxd",
        "rdma/libibverbs.pxi",
    ]
)


# From PyCA
class SphinxBuild(Command):
    description = "build documentation using Sphinx"
    user_options = [
        ("builder=", "b", "builder to use; default is html"),
        ("all", "a", "write all files; default is to only write new and changed files"),
        ("reload-env", "E", "don't use a saved environment, always read all files"),
        ("out-dir=", "o", "path where output is stored (default: doc/<builder>)"),
        ("cache-dir=", "d", "path for the cached environment and doctree files (default: outdir/.doctrees)"),
        ("conf-dir=", "c", "path where configuration file (conf.py) is located (default: same as source-dir)"),
        ("set=", "D", "<setting=value> override a setting in configuration"),
        ("no-color", "N", "do not do colored output"),
        ("pdb", "P", "run Pdb on exception"),
    ]
    boolean_options = ["all", "reload-env", "no-color", "pdb"]

    def initialize_options(self):
        self.sphinx_args = []
        self.builder = None
        self.all = False
        self.reload_env = False
        self.out_dir = None
        self.cache_dir = None
        self.conf_dir = None
        self.set = None
        self.no_color = False
        self.pdb = False
        self.build = None
        self.build_lib = None

    def finalize_options(self):
        self.set_undefined_options(
            "build",
            ("build_lib", "build_lib")
        )
        self.sphinx_args.append("sphinx-build")

        if self.builder is None:
            self.builder = "html"
        self.sphinx_args.extend(["-b", self.builder])

        if self.all:
            self.sphinx_args.append("-a")
        if self.reload_env:
            self.sphinx_args.append("-E")
        if self.no_color or ("PS1" not in os.environ and "PROMPT_COMMAND" not in os.environ):
            self.sphinx_args.append("-N")
        if not self.distribution.verbose:
            self.sphinx_args.append("-q")
        if self.pdb:
            self.sphinx_args.append("-P")

        if self.cache_dir is not None:
            self.sphinx_args.extend(["-d", self.cache_dir])
        if self.conf_dir is not None:
            self.sphinx_args.extend(["-c", self.conf_dir])
        if self.set is not None:
            self.sphinx_args.extend(["-D", self.set])

        if self.out_dir is None:
            self.out_dir = os.path.join("doc", self.builder)
        else:
            self.source_dir = "doc"

        self.sphinx_args.extend([self.source_dir, self.out_dir])

    def run(self):
        try:
            import sphinx
        except ImportError:
            log.info(
                "Sphinx not installed -- skipping documentation. ({})".format(
                    sys.exc_info()[1],
                ),
            )
            return

        if not os.path.exists(self.out_dir):
            if self.dry_run:
                self.announce(
                    "skipping creation of directory {} (dry run)".format(self.out_dir),
                )
            else:
                self.announce(
                    "creating directory {}".format(self.out_dir),
                )
                os.makedirs(self.out_dir)
        if self.dry_run:
            self.announce(
                "skipping {} (dry run)".format(" ".join(self.sphinx_args)),
            )
        else:
            self.announce("running {}".format(" ".join(self.sphinx_args)))
            opath = sys.path
            try:
                # We need to point Sphinx at the built library, including
                # the extension module so that autodoc works properly.
                sys.path.insert(0, os.path.realpath(self.build_lib))
                sphinx.main(self.sphinx_args)
            finally:
                sys.path = opath


rdma_init = importlib.machinery.SourceFileLoader("__tmp__", "rdma/__init__.py").load_module()


setup(
    name="rdma",
    version=rdma_init.__version__,
    description="RDMA functionality for python",
    ext_modules=[ibverbs_module],
    packages=["rdma", "libibtool"],
    scripts=["ibtool"],
    cmdclass={
        "build_ext": BuildExt,
        "docs": SphinxBuild,
    },
    platforms="ALL",
    classifiers=[
        "Development Status :: 4 - Beta",
        "License :: OSI Approved :: GPL",
        "Intended Audience :: Developers",
        "Natural Language :: English",
        "Operating System :: Linux",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.7",
    ],
)
