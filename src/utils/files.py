"""
Safe file writes

Every file the tool writes (caches, the score history, the watchlist, the
journal, the portfolio file, reports) goes through `atomic_write`: the
content goes to a uniquely named temp file in the same folder, which then
replaces the target in one step. A crash, Ctrl-C or a full disk leaves the
old file, never a truncated one, and two writers (parallel workers, or the
scheduled run next to a manual one) never share a temp file.
"""

import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Union

# Windows refuses a replace while another process has the target open (a
# reader, an antivirus scan); a short retry rides that out
_REPLACE_ATTEMPTS = 5
_REPLACE_WAIT_SECONDS = 0.1


def atomic_write(path: Union[str, Path], write: Callable[[Path], Any]) -> None:
    """Call `write(tmp_path)` to fill a temp file, then move it onto `path`."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    os.close(fd)
    tmp = Path(name)
    try:
        write(tmp)
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(tmp, target)
                return
            except PermissionError:
                if attempt == _REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(_REPLACE_WAIT_SECONDS)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_write_text(path: Union[str, Path], text: str, encoding: str = "utf-8") -> None:
    """Write text to `path` atomically (see `atomic_write`)."""
    atomic_write(path, lambda tmp: tmp.write_text(text, encoding=encoding))
