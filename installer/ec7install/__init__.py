"""EC7Wolf installer core.

Everything here is headless and importable without a GUI toolkit. The Qt shell
and the command-line front end are both thin faces on this, so that the part
that can be tested is the part that does the work. See docs/installer.md.
"""

__all__ = ["progress", "deps", "build", "install", "verify", "plan"]
