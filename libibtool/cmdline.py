# Copyright 2011 Obsidian Research Corp. GPLv2, see COPYING.
# -*- coding: utf-8 -*-

import inspect
import optparse
import os
import sys
from typing import List, Tuple


__all__ = [
    "CmdError",
    "MyOptParse",
    "get_cmd_func",
    "cmd_help",
]


class CmdError(Exception):
    """Thrown for any command line or command operation failures."""
    pass


class MyHelpFormatter(optparse.IndentedHelpFormatter):
    def format_usage(self, usage: str) -> str:
        return "{}\n".format(usage)


class MyOptParse(optparse.OptionParser):
    #: Global verbosity for exception reporting
    verbosity = 0

    def __init__(
        self,
        cmd,
        option_list: List=None,
        description=None,
        top_mod=None,
    ):
        if option_list is None:
            option_list = []
        if top_mod is None:
            self.top_mod = sys.modules["__main__"]
        else:
            self.top_mod = top_mod

        optparse.OptionParser.__init__(
            self,
            option_list=option_list,
            description=description,
            formatter=MyHelpFormatter(),
        )

        self.current_command = cmd
        self.prog = "{} {}".format(
            os.path.basename(sys.argv[0]),
            cmd.__name__[4:],
        )

    def parse_args(self, args, values=None, expected_values: int=-1) -> Tuple:
        args, values = optparse.OptionParser.parse_args(self, args, values)
        if expected_values != -1 and len(values) != expected_values:
            self.error(
                "Got {:d} arguments but expected {:d}".format(
                    len(values),
                    expected_values,
                ),
            )
        return args, values

    def get_usage(self):
        usage = inspect.getdoc(self.current_command)
        docer = None
        try:
            docer = self.current_command.__globals__[
                "{}_help".format(self.current_command.__name__)
            ]
        except KeyError:
            pass
        if docer is not None:
            usage = docer(self, self.current_command, usage)

        return self.formatter.format_usage(self.expand_prog_name(usage))

    def format_help(self, formatter=None):
        """Defer computing the help text until it is actually asked for."""
        return optparse.OptionParser.format_help(self, formatter)


default_module = __name__.rpartition(".")[0]


def get_cmd_func(name: str, top_mod=None):
    if top_mod is None:
        top_mod = sys.modules["__main__"]

    # Fetch the commands dict from the top level
    commands = top_mod.commands

    loc = commands[name]
    module = ".{}".format(name)
    func = "cmd_{}".format(name.replace("-", "_"))
    shown = True
    if loc is not None:
        if len(loc) >= 3:
            shown = loc[2]
        if len(loc) >= 2:
            func = loc[1]
        if len(loc) >= 1:
            module = loc[0]
    else:
        # If not module is specified search the top level otherwise assume it
        # is part of the default_module with a name equal to the command name.
        if getattr(top_mod, func, None):
            module = top_mod.__name__

    if module[0] == ".":
        module = default_module + module

    rmodule = sys.modules.get(module)
    if rmodule is None:
        __import__(module)
        rmodule = sys.modules[module]
    return getattr(rmodule, func), shown


def cmd_help(argv, o):
    """Display the help text
       Usage: %prog"""
    # Fetch the commands dict from the top level
    commands = o.top_mod.commands

    (args, values) = o.parse_args(argv)

    if len(argv) == 0:
        # Abuse the optparse help formatter to format the help text for
        # our commands
        class Formatter(MyHelpFormatter):
            def format_option(self, option):
                if option.action == "help":
                    self.option_strings[option] = "help"
                else:
                    self.option_strings[option] = self.option_strings[option][3:]
                return MyHelpFormatter.format_option(self, option)

        o = MyOptParse(cmd_help, top_mod=o.top_mod)
        for k in sorted(commands.keys()):
            if k == "help":
                continue
            func, shown = get_cmd_func(k, o.top_mod)
            if not shown:
                continue
            doc = inspect.getdoc(func)
            doc = [i for i in doc.split("\n") if len(i) != 0]
            o.add_option(
                "--x{}".format(str(k)),
                action="store_true",
                help=doc[0],
            )

        prog = os.path.basename(sys.argv[0])
        print(" {} - {}\n".format(prog, o.top_mod.banner))
        print("Usage: {} command [args]".format(prog))
        print()
        print(o.format_option_help(Formatter()))
        print("{} help [command] shows detailed help for each command".format(prog))
        return True

    if len(argv) == 1 and argv[0] in commands:
        func, shown = get_cmd_func(argv[0], top_mod=o.top_mod)
        o = MyOptParse(func, top_mod=o.top_mod)
        func(["--help"], o)
    else:
        print("No help text for {}".format(argv))
    return True