# 🐍 `python_debugger`: GDB-Like Interactive Debugger for Python

<div align="center">

![PyDebugger](https://img.shields.io/badge/Python-3.7%2B-blue.svg)
![Status](https://img.shields.io/badge/status-beta-important)

</div>

---

> **`python_debugger`** is a zero-dependency, drop-in Python decorator that enables interactive, GDB-style debugging sessions within any function or method. Its terminal-based interface provides powerful breakpoint management, variable inspection, stack navigation, and advanced stepping controls, all with intuitive, colorful prompts.

---

## 🚀 Features

-   **Decorate Any Function/Method**  
    Debug only what you care about — just add `@debug_function`.
-   **GDB-Inspired Command-Line Interface**  
    Step, continue, break, backtrace, watch, inspect, and modify — interactively.
-   **Breakpoint Power**
    -   Set by line number, function name, or with conditions.
    -   Ignore counts, enable/disable, and clear breakpoints flexibly.
-   **AST-Aided Function Navigation**  
    Break by function names (even inside classes or nested scopes).
-   **Full Stack Introspection**  
    Move up and down the call stack; inspect and modify any frame.
-   **Live Variable Editing**  
    Evaluate and set variables directly in the debugger.
-   **Watched Expressions**  
    Track changing variables or expressions as you step.
-   **Exception Interception**  
    Automatically drops you into the debugger at exceptions.
-   **No External Dependencies**  
    Pure standard library — plug and play.

---

## 📦 Installation

Just copy [`python_debugger.py`](./python_debugger.py) into your project — no pip required.

---

## 📝 Usage

### 1. Decorate Your Function

```python
from python_debugger import debug_function

@debug_function
def my_function(x, y):
    total = x + y
    for i in range(5):
        total *= i
    return total
```

### 2. Call as Usual

```python
result = my_function(2, 3)
```

On entry, you'll drop into an interactive debugging session **at the first line** of the decorated function.

---

## 🎮 Interactive Commands

| Command            | Alias | Description                                      |
| ------------------ | ----- | ------------------------------------------------ |
| `next`             | n     | Step to next line (step over)                    |
| `step`             | s     | Step into (calls/functions)                      |
| `continue`         | c     | Resume until next breakpoint or end              |
| `break <loc>`      | b     | Set breakpoint (`line`, `file:line`, or `func`)  |
| `break ... if ...` |       | Conditional breakpoints (e.g., `b 42 if x > 10`) |
| `clear <id\|loc>`  | cl    | Clear a breakpoint (by id or location)           |
| `clear all`        |       | Remove all breakpoints                           |
| `ignore <id> <n>`  |       | Ignore a breakpoint N times                      |
| `backtrace`        | bt    | Show current stack trace                         |
| `up [N]`           |       | Move up N frames in the stack                    |
| `down [N]`         |       | Move down N frames                               |
| `list`             | l     | Show source context at current line              |
| `printvar <expr>`  | p     | Evaluate an expression/variable in frame         |
| `setvar a = b+1`   | set   | Set variable in current frame                    |
| `watch <expr>`     |       | Add expression to watch list                     |
| `unwatch <expr>`   |       | Remove watched expression                        |
| `info ...`         |       | Show info (locals, globals, breakpoints, etc.)   |
| `finish`           | fin   | Run until function return                        |
| `rununtil <line>`  | until | Run until specific line                          |
| `quit`             | q     | Exit debugger                                    |
| `help`             | h     | Show command help                                |

> Use `help <command>` or `help` for more details.

---

## 🌈 Terminal Output

-   Colorful, clear line markers and stack traces
-   Contextual prompts showing file, line, and function
-   Intuitive watched variable displays
-   Error messages highlighted for visibility

---

## 💡 Examples

#### Breakpoints by Function Name

```python
b my_function      # At function start
b MyClass.method   # For methods inside classes
```

#### Conditional Breakpoints

```python
b 27 if x > 5
```

#### Watching Expressions

```python
watch total
watch mylist[-1]
```

#### Modifying Variables on the Fly

```python
set count = 42
```

---

## 🧩 Integration

-   Works with **any** Python 3.7+ codebase
-   No special environment needed (Unix, Windows, macOS)
-   Decorate multiple functions for targeted debugging
-   Can be used inside Jupyter (though CLI interface is terminal-based)

---

## ⚙️ API Reference

### `@debug_function`

-   Decorator for functions/methods
-   **Entry triggers debugger** before first line
-   Exits debugger on function return or `quit`

### Advanced: Programmatic Entry

You may invoke the debugger manually for advanced control (see source code for details).

---

## 🧪 Testing

```bash
python -m python_debugger   # (if you provide a test harness)
```

Or add the decorator to your own functions.

---

## 🛠️ Troubleshooting

-   If the debugger doesn't start:  
    Ensure you called a function decorated with `@debug_function`.
-   If running inside an IDE:  
    For best results, use a standard terminal.

---

## ✨ Credits

Developed by Giovanni Sabatelli.  
Inspired by GDB.

---

<div align="center" style="margin-top: 2em">
    <strong>Debug like a pro. Stay in the zone.</strong>
</div>
