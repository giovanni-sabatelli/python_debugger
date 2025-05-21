from python_debugger import debug_function, _TermColors

@debug_function
class MyClassDemo:
    """A demo class to test debugging of methods and AST breakpoint resolution."""

    class_var = 100

    def __init__(
        self, val
    ):  # Not decorated by default, but called from decorated scope
        self.instance_var = val
        print(f"  (MyClassDemo.__init__ called with val={val})")

    @debug_function
    def my_method(self, factor):
        """A demo method inside MyClassDemo."""
        local_to_method = self.instance_var * factor
        print(f"  (Inside MyClassDemo.my_method, local_to_method={local_to_method})")
        if local_to_method > 20:
            self.another_method(local_to_method)
        return local_to_method + self.class_var

    def another_method(self, val_in):  # Undecorated
        print(f"    (Inside MyClassDemo.another_method with {val_in})")
        return val_in / 2.0


@debug_function
def top_level_function_demo(x, y):
    """A top-level function for demonstrating the debugger."""
    print(f"  (top_level_function_demo called with x={x}, y={y})")
    res = x + y
    if res > 5:
        mc_instance = MyClassDemo(res)
        final = mc_instance.my_method(2)
        print(f"  (Final result from MyClassDemo call: {final})")
    else:
        final = res
        print(f"  (Simple result: {final})")

    @debug_function
    def nested_func_demo(p):
        """A nested function for testing breakpoint resolution and nested debugger activation."""
        print(f"    (Inside nested_func_demo with p={p})")
        return p * p

    nf_res = nested_func_demo(final)
    print(f"  (Nested function result: {nf_res})")
    return nf_res


if __name__ == "__main__":
    print(f"{_TermColors.BOLD}Starting debugger demo...{_TermColors.ENDC}")
    print("\n--- Test Case 1: Complex path with method calls ---")
    result1 = top_level_function_demo(4, 3)
    print(
        f"{_TermColors.OKGREEN}Result of top_level_function_demo(4,3): {result1}{_TermColors.ENDC}"
    )
    print("\n--- Test Case 2: Simpler path ---")
    result2 = top_level_function_demo(1, 1)
    print(
        f"{_TermColors.OKGREEN}Result of top_level_function_demo(1,1): {result2}{_TermColors.ENDC}"
    )
    print(f"\n{_TermColors.BOLD}Debugger demo finished.{_TermColors.ENDC}")
