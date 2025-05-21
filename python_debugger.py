from sys import settrace, gettrace, stdout
from inspect import ismethod, isfunction
from linecache import getline
from cmd import Cmd
from traceback import print_exception
from os import path
from re import match
from ast import NodeVisitor, parse
from collections import Counter, deque


class _TermColors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    GREY = "\033[90m"


def debug_function(obj_to_debug):
    """
    A decorator that enables a GDB-like debugger for the decorated function or method.
    Activates upon function/method entry. If applied to a class, it currently does not
    automatically decorate its methods; methods should be decorated individually.
    """

    class _BreakpointInfo:
        """Stores information and state for a single breakpoint."""

        def __init__(
            self, lineno, file_abs, condition_str=None, initial_ignore_count=0
        ):
            self.lineno = lineno
            self.file_abs = file_abs
            self.condition_str = condition_str
            self.initial_ignore_count = initial_ignore_count
            self.current_ignore_left = initial_ignore_count
            self.hit_count = 0
            self.enabled = True

        def __repr__(self):
            return (
                f"_BreakpointInfo(lineno={self.lineno}, file='{path.basename(self.file_abs)}', "
                f"cond='{self.condition_str}', ignore={self.current_ignore_left}/{self.initial_ignore_count}, "
                f"hits={self.hit_count}, enabled={self.enabled})"
            )

        def should_stop(self, frame_globals, frame_locals):
            if not self.enabled:
                return False
            self.hit_count += 1
            if self.current_ignore_left > 0:
                self.current_ignore_left -= 1
                return False
            if self.condition_str:
                try:
                    return bool(eval(self.condition_str, frame_globals, frame_locals))
                except Exception as e:
                    print(
                        f"{_TermColors.WARNING}Err evaluating BP condition '{self.condition_str}': {e}{_TermColors.ENDC}"
                    )
                    return False
            return True

    class _BreakpointManager:
        """Manages all breakpoint operations, including AST parsing and caching for function name resolution."""

        def __init__(self):
            self.breakpoints_by_file = {}
            self.ast_cache = {}
            self.next_bp_id = 1
            self.breakpoints_by_id = {}

        class _FunctionFinder(NodeVisitor):
            def __init__(self, func_name_parts):
                self.func_name_parts = func_name_parts
                self.target_lineno = None
                self._current_path = []

            def visit_FunctionDef(self, node):
                self._current_path.append(node.name)
                if (
                    len(self._current_path) == len(self.func_name_parts)
                    and self._current_path == self.func_name_parts
                ):
                    self.target_lineno = node.lineno
                if (
                    not self.target_lineno
                    and len(self._current_path) < len(self.func_name_parts)
                    and self.func_name_parts[: len(self._current_path)]
                    == self._current_path
                ):
                    self.generic_visit(node)
                self._current_path.pop()

            def visit_AsyncFunctionDef(self, node):
                self.visit_FunctionDef(node)

            def visit_ClassDef(self, node):
                self._current_path.append(node.name)
                if (
                    len(self._current_path) <= len(self.func_name_parts)
                    and self.func_name_parts[: len(self._current_path)]
                    == self._current_path
                ):
                    self.generic_visit(node)
                self._current_path.pop()

        def _load_ast_with_cache(self, filename_abs):
            try:
                mtime = path.getmtime(filename_abs)
                if (
                    filename_abs in self.ast_cache
                    and mtime == self.ast_cache[filename_abs][0]
                ):
                    return self.ast_cache[filename_abs][1]
                with open(filename_abs, "r", encoding="utf-8") as f:
                    source_code = f.read()
                tree = parse(source_code, filename=filename_abs)
                self.ast_cache[filename_abs] = (mtime, tree)
                return tree
            except (FileNotFoundError, SyntaxError, Exception):
                return None

        def _find_func_lineno_using_ast(self, filename_abs, func_spec):
            tree = self._load_ast_with_cache(filename_abs)
            _ = tree or (_FunctionFinder([]).target_lineno)  # type: ignore
            if not tree:
                return None
            finder = self._FunctionFinder(func_spec.split("."))
            finder.visit(tree)
            return finder.target_lineno

        def parse_location_string(self, loc_str, current_file_for_context):
            file_part_str, loc_part_str = (
                loc_str.rsplit(":", 1)
                if ":" in loc_str
                else (current_file_for_context, loc_str)
            )
            abs_file_path = path.abspath(file_part_str)
            try:
                return abs_file_path, int(loc_part_str)
            except ValueError:
                lineno = self._find_func_lineno_using_ast(abs_file_path, loc_part_str)
                return (abs_file_path, lineno) if lineno else (None, None)

        def add_breakpoint(
            self, file_abs, lineno, condition_str=None, initial_ignore_count=0
        ):
            if file_abs not in self.breakpoints_by_file:
                self.breakpoints_by_file[file_abs] = {}
            bp_info = _BreakpointInfo(
                lineno, file_abs, condition_str, initial_ignore_count
            )
            self.breakpoints_by_file[file_abs][lineno] = bp_info
            bp_id = self.next_bp_id
            self.next_bp_id += 1
            self.breakpoints_by_id[bp_id] = bp_info
            print(
                f"Breakpoint {bp_id} set at {path.basename(file_abs)}:{lineno}"
                + (f" if {condition_str}" if condition_str else "")
                + (
                    f" (ignore next {initial_ignore_count} hits)"
                    if initial_ignore_count > 0
                    else ""
                )
            )
            return bp_id

        def clear_breakpoint(self, bp_id_or_loc_str, current_file_for_context):
            bp_to_remove_id = (
                bp_id_or_loc_str if isinstance(bp_id_or_loc_str, int) else None
            )
            if not bp_to_remove_id:
                file_abs, lineno = self.parse_location_string(
                    bp_id_or_loc_str, current_file_for_context
                )
                if (
                    file_abs
                    and lineno
                    and file_abs in self.breakpoints_by_file
                    and lineno in self.breakpoints_by_file[file_abs]
                ):
                    bp_info = self.breakpoints_by_file[file_abs][lineno]
                    for bp_id, info in self.breakpoints_by_id.items():
                        if info == bp_info:
                            bp_to_remove_id = bp_id
                            break
                else:
                    return False
            if bp_to_remove_id and bp_to_remove_id in self.breakpoints_by_id:
                bp_info = self.breakpoints_by_id.pop(bp_to_remove_id)
                del self.breakpoints_by_file[bp_info.file_abs][bp_info.lineno]
                if not self.breakpoints_by_file[bp_info.file_abs]:
                    del self.breakpoints_by_file[bp_info.file_abs]
                print(f"Breakpoint {bp_to_remove_id} cleared.")
                return True
            return False

        def clear_all_breakpoints(self):
            self.breakpoints_by_file.clear()
            self.breakpoints_by_id.clear()
            print("All breakpoints cleared.")

        def check_breakpoint(self, file_abs, lineno, frame_globals, frame_locals):
            if (
                file_abs in self.breakpoints_by_file
                and lineno in self.breakpoints_by_file[file_abs]
            ):
                bp_info = self.breakpoints_by_file[file_abs][lineno]
                if bp_info.should_stop(frame_globals, frame_locals):
                    return bp_info
            return None

        def set_ignore_count(self, bp_id, count):
            if bp_id in self.breakpoints_by_id:
                bp_info = self.breakpoints_by_id[bp_id]
                bp_info.initial_ignore_count = count
                bp_info.current_ignore_left = count
                print(f"BP {bp_id} will ignore {count} hits.")
                return True
            print(f"{_TermColors.WARNING}BP ID {bp_id} not found.{_TermColors.ENDC}")
            return False

        def list_breakpoints(self):
            if not self.breakpoints_by_id:
                print("  No breakpoints set.")
                return
            print(
                f"{_TermColors.HEADER}Breakpoints:{_TermColors.ENDC}\n  ID  Enb Hits Ignore Condition                           Location\n  --- --- ---- ------ ----------------------------------- --------------------"
            )
            for bp_id, bp in sorted(self.breakpoints_by_id.items()):
                print(
                    f"  {bp_id:<3} {'y' if bp.enabled else 'n':<3} {bp.hit_count:<4} {str(bp.current_ignore_left)+'/'+str(bp.initial_ignore_count):<6} {(bp.condition_str or ''):<35.35} {path.basename(bp.file_abs)}:{bp.lineno}"
                )

    class _StateManager:
        """Manages the debugger's stepping state."""

        def __init__(self):
            self.request_stop_at_next_suitable_event = True  # True for initial entry
            self.step_into = False
            self.step_over = False
            self.step_over_target_depth = -1
            self.step_out = False
            self.step_out_target_depth = -1
            self.run_until_line_info = None

        def reset_stepping_flags(self):
            self.step_into = False
            self.step_over = False
            self.step_out = False

        def configure_for_run(self):
            self.request_stop_at_next_suitable_event = False
            self.reset_stepping_flags()
            self.run_until_line_info = None

        def configure_for_step_into(self):
            self.request_stop_at_next_suitable_event = True
            self.step_into = True
            self.step_over = False
            self.step_out = False
            self.run_until_line_info = None

        def configure_for_step_over(self, depth):
            self.request_stop_at_next_suitable_event = True
            self.step_over = True
            self.step_into = False
            self.step_out = False
            self.step_over_target_depth = depth
            self.run_until_line_info = None

        def configure_for_step_out(self, depth):
            self.request_stop_at_next_suitable_event = True
            self.step_out = True
            self.step_into = False
            self.step_over = False
            self.step_out_target_depth = depth
            self.run_until_line_info = None

        def configure_for_run_until(self, file, line):
            self.request_stop_at_next_suitable_event = True
            self.reset_stepping_flags()
            self.run_until_line_info = (file, line)

    class PyDebugger(Cmd):
        """PyDebugger is the main debugger class, providing a command-line interface and managing debug sessions."""

        prompt_template = f"({_TermColors.OKBLUE}pydbg{_TermColors.ENDC}) "
        intro_message = f"{_TermColors.BOLD}Welcome to PyDebugger. Type 'help' or '?' for commands.{_TermColors.ENDC}"
        current_line_marker = f"{_TermColors.OKGREEN}--->{_TermColors.ENDC} "

        def __init__(self, entry_exec_frame):
            super().__init__()
            self.execution_frame = entry_exec_frame
            self.interaction_frame = entry_exec_frame
            self._full_stack_at_stop = []
            self._interaction_stack_idx = 0
            self.state_manager = _StateManager()  # Initial state requests stop
            self.breakpoint_manager = _BreakpointManager()
            self.watched_expressions = []
            self.command_history = deque(maxlen=100)
            self.last_non_empty_cmd = ""
            self.quit_debugger = False
            self.aliases = {
                "n": "next",
                "s": "step",
                "c": "continue",
                "q": "quit",
                "bt": "backtrace",
                "p": "printvar",
                "b": "break",
                "cl": "clear",
                "l": "list",
                "h": "help",
                "set": "setvar",
                "fin": "finish",
                "until": "rununtil",
                "up": "up_stack",
                "down": "down_stack",
                "info": "info",
                "watch": "watch_expr",
                "unwatch": "unwatch_expr",
                "ignore": "ignore_breakpoint",
            }
            self._capture_full_stack(self.execution_frame)
            self.update_prompt()
            print(self.intro_message)
            # Initial print_current_location and cmdloop are now deferred to the first trace_dispatch stop

        def _get_frame_depth(self, frm):
            depth = 0
            temp_frm = frm
            while temp_frm:
                depth += 1
                temp_frm = temp_frm.f_back
            return depth

        def _capture_full_stack(self, most_recent_frame):
            self._full_stack_at_stop = []
            frm = most_recent_frame
            while frm:
                self._full_stack_at_stop.append(frm)
                frm = frm.f_back
            if (
                self.execution_frame
                and self.execution_frame in self._full_stack_at_stop
            ):
                self._interaction_stack_idx = self._full_stack_at_stop.index(
                    self.execution_frame
                )
                self.interaction_frame = self.execution_frame
            elif self._full_stack_at_stop:
                self._interaction_stack_idx = 0
                self.interaction_frame = self._full_stack_at_stop[0]

        def update_prompt(self):
            frm = self.interaction_frame
            ind = ""
            if frm:
                if self.interaction_frame != self.execution_frame:
                    ind = f" (inspecting frame {self._interaction_stack_idx})"
                self.prompt = f"({_TermColors.OKBLUE}pydbg{_TermColors.ENDC} {_TermColors.GREY}{path.basename(frm.f_code.co_filename)}:{frm.f_lineno} {frm.f_code.co_name}(){ind}{_TermColors.ENDC}) "
            else:
                self.prompt = self.prompt_template

        def print_current_location(self, frm, reason=""):
            if not frm:
                return
            fn, ln, nm = frm.f_code.co_filename, frm.f_lineno, frm.f_code.co_name
            if reason:
                print(f"{_TermColors.GREY}{reason} at:{_TermColors.ENDC}")
            idx = (
                self._full_stack_at_stop.index(frm)
                if self._full_stack_at_stop and frm in self._full_stack_at_stop
                else "?"
            )
            print(
                f" Frame {idx}: {_TermColors.BOLD}{path.basename(fn)}:{ln} {nm}(){_TermColors.ENDC}"
            )
            ctx = 5
            sline = max(1, ln - (ctx // 2))
            eline = sline + ctx - 1
            for i in range(sline, eline + 1):
                txt = getline(fn, i).rstrip("\n")
                if txt:
                    pfx = (
                        self.current_line_marker
                        if i == ln and frm == self.execution_frame
                        else "     "
                    )
                    print(
                        f" {pfx}{i:4d} {_TermColors.OKCYAN if i==ln else ''}{txt}{_TermColors.ENDC if i==ln else ''}"
                    )
            print()

        def _print_watched_expressions(self):
            if self.watched_expressions and self.interaction_frame:
                print(
                    f"{_TermColors.HEADER}Watched Expressions (frame {self._interaction_stack_idx}):{_TermColors.ENDC}"
                )
                for i, ex in enumerate(self.watched_expressions):
                    try:
                        v = eval(
                            ex,
                            self.interaction_frame.f_globals,
                            self.interaction_frame.f_locals,
                        )
                        print(f"  {i}: {ex} = {repr(v)}")
                    except Exception as e:
                        print(f"  {i}: {ex} = Error: {e}")
                print()

        def trace_dispatch(self, frm, event, arg):
            if self.quit_debugger:
                settrace(None)
                return None
            self.execution_frame = frm

            stop_now = self.state_manager.request_stop_at_next_suitable_event
            self.state_manager.request_stop_at_next_suitable_event = (
                False  # Assume continue, cmds will set True if needed
            )

            current_file_abs = path.abspath(frm.f_code.co_filename)
            current_depth = self._get_frame_depth(frm)
            reason_for_stop = (
                "Initial entry" if stop_now else None
            )  # Default reason if stop was requested

            if event == "call":
                if self.state_manager.step_into:
                    stop_now = True
                    reason_for_stop = f"Step into {frm.f_code.co_name}"
                elif self.state_manager.step_over or self.state_manager.step_out:
                    stop_now = False  # Don't stop at call
                elif stop_now:
                    pass  # Initial entry, stop at call
            elif event == "line":
                if self.state_manager.run_until_line_info:
                    r_file, r_ln = self.state_manager.run_until_line_info
                    if current_file_abs == r_file and frm.f_lineno == r_ln:
                        stop_now = True
                        reason_for_stop = "Until"
                        self.state_manager.run_until_line_info = None
                elif self.state_manager.step_into:
                    stop_now = True
                    reason_for_stop = "Step"
                elif (
                    self.state_manager.step_over
                    and current_depth <= self.state_manager.step_over_target_depth
                ):
                    stop_now = True
                    reason_for_stop = "Next"
                elif (
                    self.state_manager.step_out
                    and current_depth <= self.state_manager.step_out_target_depth
                ):
                    stop_now = True
                    reason_for_stop = "Finish"
                elif stop_now and reason_for_stop == "Initial entry":
                    reason_for_stop = "First line"  # Refine reason
            elif event == "exception":
                stop_now = True
                reason_for_stop = "Exception"

            if not stop_now:  # Check breakpoints if not already stopping
                bp_info = self.breakpoint_manager.check_breakpoint(
                    current_file_abs, frm.f_lineno, frm.f_globals, frm.f_locals
                )
                if bp_info:
                    stop_now = True
                    reason_for_stop = f"BP {self._get_bp_id(bp_info)}"

            if stop_now:
                self._capture_full_stack(self.execution_frame)
                self.interaction_frame = self.execution_frame
                self._interaction_stack_idx = 0
                self.update_prompt()
                self.print_current_location(self.interaction_frame, reason_for_stop)
                self._print_watched_expressions()
                if event == "exception":
                    exc_type, exc_val, exc_tb = arg
                    print(f"{_TermColors.FAIL}Exception:{_TermColors.ENDC}")
                    print_exception(
                        exc_type, exc_val, exc_tb, None, stdout
                    )

                # Reset stepping flags *after* they caused a stop and before cmdloop (which might set new ones)
                # The request_stop_at_next_suitable_event is already False, so commands like 'c' work.
                # Stepping commands will set request_stop_at_next_suitable_event = True again.
                if (
                    self.state_manager.step_into
                    or self.state_manager.step_over
                    or self.state_manager.step_out
                ):
                    self.state_manager.reset_stepping_flags()

                self.cmdloop()
                if self.quit_debugger:
                    settrace(None)
                    return None

            return self.trace_dispatch

        def _get_bp_id(self, bp_info_obj):
            for id, info in self.breakpoint_manager.breakpoints_by_id.items():
                if info == bp_info_obj:
                    return id
            return "?"

        def precmd(self, line):
            line = line.strip()
            if line:
                self.command_history.append(line)
                self.last_non_empty_cmd = line
            if not line:
                return ""
            parts = line.split(maxsplit=1)
            cmd_name = parts[0]
            if cmd_name in self.aliases:
                return (
                    f"{self.aliases[cmd_name]} {parts[1]}"
                    if len(parts) > 1
                    else self.aliases[cmd_name]
                )
            return line

        def default(self, line):
            if self.interaction_frame:
                try:
                    print(
                        repr(
                            eval(
                                line,
                                self.interaction_frame.f_globals,
                                self.interaction_frame.f_locals.copy(),
                            )
                        )
                    )
                except Exception as e:
                    print(f"{_TermColors.FAIL}Error: '{line}' ({e}){_TermColors.ENDC}")
            else:
                print(f"{_TermColors.FAIL}No active frame.{_TermColors.ENDC}")

        def emptyline(self):
            if self.last_non_empty_cmd:
                print(
                    f"({_TermColors.GREY}Repeating: {self.last_non_empty_cmd}{_TermColors.ENDC})"
                )
                self.onecmd(self.last_non_empty_cmd)

        def do_help(self, arg):
            """List available commands with "help" or detailed help with "help cmd"."""
            if arg:
                orig_arg, act_cmd, is_alias = arg, arg, False
                if arg in self.aliases:
                    act_cmd = self.aliases[arg]
                    is_alias = True
                try:
                    doc = getattr(self, "do_" + act_cmd).__doc__
                    if doc:
                        print(
                            (
                                f"'{orig_arg}' is alias for '{act_cmd}'.\n"
                                if is_alias
                                else ""
                            )
                            + doc.strip()
                        )
                    else:
                        print(
                            f"No help for '{act_cmd}'.{(f"\n'{orig_arg}' is alias for '{act_cmd}'." if is_alias else "")}"
                        )
                except AttributeError:
                    print(f"No help for '{orig_arg}'. Unknown.")
            else:
                super().do_help(arg)
                print(f"\n{_TermColors.BOLD}Aliases:{_TermColors.ENDC}")
                max_len = (
                    max(len(a) for a in self.aliases.keys()) if self.aliases else 0
                )
                for a, c in sorted(self.aliases.items()):
                    print(f"  {a:<{max_len+2}} -> {c}")
                print(
                    f"\n{_TermColors.GREY}Use 'help <alias>' for specific command help.{_TermColors.ENDC}"
                )

        def do_next(self, arg):
            """n: Step to next line (step over calls)."""
            self.state_manager.configure_for_step_over(
                self._get_frame_depth(self.execution_frame)
            )
            return True

        def do_step(self, arg):
            """s: Step into call or to next line."""
            self.state_manager.configure_for_step_into()
            return True

        def do_continue(self, arg):
            """c: Continue execution."""
            self.state_manager.configure_for_run()
            print(
                f"{_TermColors.OKGREEN}Continuing...{_TermColors.ENDC}"
                if self.execution_frame
                else ""
            )
            return True

        def do_quit(self, arg):
            """q: Quit debugger."""
            print(f"{_TermColors.WARNING}Quitting.{_TermColors.ENDC}")
            self.quit_debugger = True
            settrace(None)
            return True

        def do_EOF(self, arg):
            """Handles Ctrl-D as quit."""
            return self.do_quit(arg)

        def do_backtrace(self, arg):
            """bt: Print call stack. '*' exec frame, '->' inspect frame."""
            if not self._full_stack_at_stop:
                self._capture_full_stack(self.execution_frame or self.interaction_frame)
            if not self._full_stack_at_stop:
                print("No stack.")
                return
            print(
                f"{_TermColors.HEADER}Call Stack (most recent first - index 0):{_TermColors.ENDC}"
            )
            for idx, frm in enumerate(self._full_stack_at_stop):
                pfx = "->" if frm == self.interaction_frame else "  "
                exm = "*" if frm == self.execution_frame else " "
                print(
                    f"{pfx}{exm}#{idx}: {_TermColors.OKCYAN}{frm.f_code.co_name}(){_TermColors.ENDC} at {_TermColors.GREY}{path.basename(frm.f_code.co_filename)}:{frm.f_lineno}{_TermColors.ENDC}"
                )
            print()

        def do_printvar(self, arg):
            """p <expr>: Evaluate and print expression in current interaction frame."""
            if not arg:
                print("Arg required.")
                return
            if not self.interaction_frame:
                print("No frame.")
                return
            try:
                print(
                    f"{arg} = {repr(eval(arg, self.interaction_frame.f_globals, self.interaction_frame.f_locals))}"
                )
            except Exception as e:
                print(f"{_TermColors.FAIL}Error: {e}{_TermColors.ENDC}")

        def do_setvar(self, arg):
            """set <var> = <expr>: Set local variable in current interaction frame."""
            if not self.interaction_frame:
                print("No frame.")
                return
            m = match(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.*)$", arg)
            if not m:
                print("Usage: set <var> = <expr>")
                return
            var, expr = m.groups()
            try:
                val = eval(
                    expr,
                    self.interaction_frame.f_globals,
                    self.interaction_frame.f_locals,
                )
                self.interaction_frame.f_locals[var] = val
                print(f"Set {var}={repr(val)}")
            except Exception as e:
                print(f"{_TermColors.FAIL}Error: {e}{_TermColors.ENDC}")

        def do_break(self, arg):
            """b [<file>:]<line|func> [if <cond>]: Set breakpoint."""
            if not arg:
                print("Location required.")
                return
            parts = arg.split(" if ", 1)
            loc = parts[0]
            cond = parts[1] if len(parts) > 1 else None
            ctx_file = (
                self.interaction_frame.f_code.co_filename
                if self.interaction_frame
                else __file__
            )
            file_abs, line_no = self.breakpoint_manager.parse_location_string(
                loc, ctx_file
            )
            if file_abs and line_no:
                self.breakpoint_manager.add_breakpoint(file_abs, line_no, cond)
            self.do_info("breakpoints")

        def do_clear(self, arg):
            """cl <id|loc|all>: Clear breakpoint(s)."""
            if not arg:
                print("Arg required.")
                return
            if arg.lower() == "all":
                self.breakpoint_manager.clear_all_breakpoints()
                return
            try:
                self.breakpoint_manager.clear_breakpoint(int(arg), None)
            except ValueError:
                self.breakpoint_manager.clear_breakpoint(
                    arg,
                    (
                        self.interaction_frame.f_code.co_filename
                        if self.interaction_frame
                        else __file__
                    ),
                )
            self.do_info("breakpoints")

        def do_ignore_breakpoint(self, arg):
            """ignore <bp_id> <count>: Set ignore count for breakpoint."""
            p = arg.split()
            if len(p) != 2:
                print("Usage: ignore <id> <count>")
                return
            try:
                self.breakpoint_manager.set_ignore_count(int(p[0]), int(p[1]))
            except ValueError:
                print("Invalid id or count.")

        def do_list(self, arg):
            """l: List source around current interaction frame line."""
            if not self.interaction_frame:
                print("No frame.")
                return
            self.print_current_location(
                self.interaction_frame, f"Listing frame {self._interaction_stack_idx}"
            )

        def do_rununtil(self, arg):
            """until <line>: Continue until line in current exec frame's file."""
            if not arg:
                print("Line # required.")
                return
            if not self.execution_frame:
                print("No exec frame.")
                return
            try:
                ln = int(arg)
                file_abs = path.abspath(self.execution_frame.f_code.co_filename)
                self.state_manager.configure_for_run_until(file_abs, ln)
                print(
                    f"{_TermColors.OKGREEN}Running until {ln} in {path.basename(file_abs)}...{_TermColors.ENDC}"
                )
                return True
            except ValueError:
                print(f"{_TermColors.FAIL}Invalid line #: {arg}{_TermColors.ENDC}")

        def do_finish(self, arg):
            """fin: Execute until current exec function returns."""
            if not self.execution_frame or not self.execution_frame.f_back:
                print("Cannot 'finish'.")
                return False
            self.state_manager.configure_for_step_out(
                self._get_frame_depth(self.execution_frame.f_back)
            )
            print(
                f"{_TermColors.OKGREEN}Finishing {self.execution_frame.f_code.co_name}...{_TermColors.ENDC}"
            )
            return True

        def do_info(self, arg):
            """info <subtopic>: Display info (locals,globals,breakpoints,stack,heap,frame,history,watch)."""
            if not arg:
                print("Subtopic required.")
                return
            frm = self.interaction_frame
            if not frm and arg not in ["breakpoints", "heap", "history", "watch"]:
                print("No frame.")
                return
            if arg == "locals":
                if frm:
                    print(
                        f"{_TermColors.HEADER}Locals (frame {self._interaction_stack_idx}):{_TermColors.ENDC}"
                    )
                    (
                        [print(f"  {n}:{repr(v)}") for n, v in frm.f_locals.items()]
                        if frm.f_locals
                        else print("  No locals.")
                    )
            elif arg == "globals":
                if frm:
                    print(
                        f"{_TermColors.HEADER}Globals (frame {self._interaction_stack_idx},excerpt):{_TermColors.ENDC}"
                    )
                    c = 0
                    [
                        [print(f"  {n}:{repr(v)}"), c := c + 1]
                        for n, v in frm.f_globals.items()
                        if not (n.startswith("__") and n.endswith("__")) and c < 25
                    ] or (c > 25 and print("  ..."))
            elif arg == "breakpoints":
                self.breakpoint_manager.list_breakpoints()
            elif arg == "stack":
                self.do_backtrace("")
            elif arg == "heap":
                print(f"{_TermColors.HEADER}Heap Summary:{_TermColors.ENDC}")
                import gc

                gc.collect()
                o = gc.get_objects()
                t = Counter(type(obj).__name__ for obj in o)
                print("  Top 20:")
                [print(f"    {ty:<30}:{ct}") for ty, ct in t.most_common(20)]
                print(f"  Total: {len(o)}")
            elif arg == "frame":
                if frm:
                    print(
                        f"{_TermColors.HEADER}Frame Info (idx {self._interaction_stack_idx}):{_TermColors.ENDC}"
                    )
                    print(
                        f"  Func:{frm.f_code.co_name}\n  File:{frm.f_code.co_filename}\n  Line:{frm.f_lineno}\n  Byte:{frm.f_lasti}"
                    )
                    print(
                        f"{_TermColors.WARNING}Not exec frame.{_TermColors.ENDC}"
                        if frm != self.execution_frame
                        else ""
                    )
            elif arg == "history":
                print(f"{_TermColors.HEADER}History:{_TermColors.ENDC}")
                (
                    [
                        print(
                            f"  {len(self.command_history)-min(20,len(self.command_history))+i :3}:{item}"
                        )
                        for i, item in enumerate(list(self.command_history)[-20:])
                    ]
                    if self.command_history
                    else print("  No history.")
                )
            elif arg == "watch":
                (
                    self._print_watched_expressions()
                    if self.watched_expressions
                    else print("  No watched expressions.")
                )
            else:
                print(f"Unknown info: {arg}.")

        def do_up_stack(self, arg_str):
            """up [N]: Move N levels up call stack (older frame, higher index)."""
            if not self._full_stack_at_stop:
                print("No stack.")
                return
            c = 1
            idx = self._interaction_stack_idx
            if arg_str:
                try:
                    c = int(arg_str)
                except ValueError:
                    print("Invalid count.")
                    return
            n_idx = idx + c
            if 0 <= n_idx < len(self._full_stack_at_stop):
                self._interaction_stack_idx = n_idx
                self.interaction_frame = self._full_stack_at_stop[n_idx]
                self.update_prompt()
                self.print_current_location(self.interaction_frame, f"Frame {n_idx}")
            else:
                print("Cannot move further up.")

        def do_down_stack(self, arg_str):
            """down [N]: Move N levels down call stack (newer frame, lower index)."""
            if not self._full_stack_at_stop:
                print("No stack.")
                return
            c = 1
            idx = self._interaction_stack_idx
            if arg_str:
                try:
                    c = int(arg_str)
                except ValueError:
                    print("Invalid count.")
                    return
            n_idx = idx - c
            if 0 <= n_idx < len(self._full_stack_at_stop):
                self._interaction_stack_idx = n_idx
                self.interaction_frame = self._full_stack_at_stop[n_idx]
                self.update_prompt()
                self.print_current_location(self.interaction_frame, f"Frame {n_idx}")
            else:
                print("Cannot move further down.")

        def do_watch_expr(self, arg):
            """watch <expr>: Add expression to watch list."""
            if not arg:
                print("Expr required.")
                return
            if arg not in self.watched_expressions:
                self.watched_expressions.append(arg)
                print(f"Watching: {arg}")
            else:
                print(f"Already watching: {arg}")
            self._print_watched_expressions()

        def do_unwatch_expr(self, arg):
            """unwatch <expr|idx>: Remove expression from watch list."""
            if not arg:
                print("Expr or idx required.")
                return
            try:
                idx = int(arg)
                if 0 <= idx < len(self.watched_expressions):
                    print(f"Unwatched: {self.watched_expressions.pop(idx)}")
                else:
                    print(f"Invalid idx: {idx}")
            except ValueError:
                if arg in self.watched_expressions:
                    self.watched_expressions.remove(arg)
                    print(f"Unwatched: {arg}")
                else:
                    print(f"Not watching: {arg}")

    if not (isfunction(obj_to_debug) or ismethod(obj_to_debug)):
        return obj_to_debug

    def actual_function_wrapper(*args, **kwargs):
        active_trace_func = gettrace()
        is_already_tracing_with_our_debugger = False
        if (
            active_trace_func
            and hasattr(active_trace_func, "__self__")
            and isinstance(active_trace_func.__self__, PyDebugger)
            and active_trace_func.__name__ == "trace_dispatch"
        ):
            is_already_tracing_with_our_debugger = True

        if is_already_tracing_with_our_debugger:
            return obj_to_debug(*args, **kwargs)
        else:
            original_trace_func = active_trace_func
            debugger_instance_holder = [None]

            def _initial_trace_for_this_func_entry(frame, event, arg):
                if event == "call" and frame.f_code == obj_to_debug.__code__:
                    dbg = PyDebugger(entry_exec_frame=frame)
                    debugger_instance_holder[0] = dbg
                    return dbg.trace_dispatch(frame, event, arg)
                return _initial_trace_for_this_func_entry

            settrace(_initial_trace_for_this_func_entry)
            result = None
            try:
                result = obj_to_debug(*args, **kwargs)
            except Exception:
                if not debugger_instance_holder[0]:
                    print(
                        f"{_TermColors.FAIL}Critical: Debugger for {obj_to_debug.__name__} failed init.{_TermColors.ENDC}"
                    )
                raise
            finally:
                current_trace = gettrace()
                if current_trace is _initial_trace_for_this_func_entry or (
                    debugger_instance_holder[0]
                    and hasattr(debugger_instance_holder[0], "trace_dispatch")
                    and current_trace == debugger_instance_holder[0].trace_dispatch
                ):
                    settrace(original_trace_func)
            return result

    return actual_function_wrapper
