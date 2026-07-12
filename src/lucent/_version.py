"""Single source of the package version.

A leaf module so ``assess`` can cite the version without importing the ``lucent`` package
top-level, which would form a module-level import cycle (``assess`` → ``__init__`` →
``graph`` → ``assess``) — exactly the kind of thing lucent's brittle lens flags.
"""

from __future__ import annotations

__version__ = "0.1.0"
