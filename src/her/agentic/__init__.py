"""Agentic tools package.

Importing this package triggers tool registration: every domain submodule
runs its ``@tool()`` decorators, which append :class:`Tool` entries to
:data:`TOOLS` and index them in :func:`by_name`.

To add a new tool, write an async function with type hints and a
Google-style docstring in the appropriate domain file (``macos.py``,
``calendar.py``, ``screen.py``, ``web.py``, ``accessibility.py``) and
decorate it with :func:`tool`. The JSON schema sent to OpenAI is derived
automatically. To start a new domain, create ``my_domain.py``, add
``from . import my_domain  # noqa: F401`` to the registration block below,
and you're done.
"""
from __future__ import annotations

from .registry import TOOLS, Tool, by_name, openai_specs, tool

# Domain modules — importing them runs their @tool() decorators. Order is
# not significant; duplicates raise at registration time.
from . import accessibility  # noqa: F401,E402
from . import calendar  # noqa: F401,E402
from . import email  # noqa: F401,E402
from . import macos  # noqa: F401,E402
from . import screen  # noqa: F401,E402
from . import skills  # noqa: F401,E402
from . import web  # noqa: F401,E402

__all__ = ["TOOLS", "Tool", "by_name", "openai_specs", "tool"]
