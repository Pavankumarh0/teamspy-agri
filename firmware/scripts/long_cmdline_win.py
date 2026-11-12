"""
Workaround for a Windows-only build failure in this project.

Symptom
-------
    xtensa-esp32-elf-g++: error: CreateProcess: No such file or directory

seen only when compiling with TFT_eSPI in the dependency graph. Raising
SCons' MAXLINELENGTH instead produces the blunter

    The command line is too long.

Cause
-----
The ESP32 framework contributes well over a hundred include paths, each
carrying this machine's profile path, so a single compile command runs to
roughly 32,000 characters. cmd.exe refuses anything past 8,191, so SCons must
spill the arguments into a response file and pass it to GCC as @file. That part
is unavoidable.

The breakage is in how the arguments are written into that file. SCons quotes
any argument containing a space, which is correct in principle, but this
project's path contains spaces ("Pavan Kumar H") and GCC treats a backslash
inside a quoted response-file argument as an escape character. So

    "-IC:\\Users\\Pavan Kumar H\\.platformio\\packages\\..."

has its \\U, \\P and \\. read as escape sequences, the include paths are
corrupted, GCC loses track of its own installation, and the missing cc1plus
surfaces as "No such file or directory".

Fix
---
Normalise the separators to forward slashes before the argument is written.
Windows GCC accepts forward slashes in paths, and they carry no escape
meaning, so quoting then behaves as intended.

This is the remedy SCons documents for GCC on Windows; see the TempFileMunge
docstring in SCons/Platform/__init__.py, which carries this same example.

A heavier alternative, if this ever stops being enough, is to relocate
PlatformIO's core_dir to a path containing no spaces, which removes the
problem at the source rather than escaping around it.
"""

import re
import sys

from SCons.Subst import quote_spaces

Import("env")  # noqa: F821  - injected by SCons

# A backslash that is not already escaping a quote or another backslash.
WINPATHSEP_RE = re.compile(r"\\([^\"'\\]|$)")


def tempfile_arg_esc_func(arg):
    """Escape one response-file argument so Windows GCC reads it intact."""
    out = quote_spaces(arg)
    if sys.platform == "win32":
        out = WINPATHSEP_RE.sub(r"/\1", out)
    return out


env.Replace(TEMPFILEARGESCFUNC=tempfile_arg_esc_func)  # noqa: F821

# Keep the response file itself on a path with no spaces, so the @file
# argument on the real command line cannot be split either.
env.Replace(TEMPFILEDIR="C:/pio-build/campusmithra/resp")  # noqa: F821
