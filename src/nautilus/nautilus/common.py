from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class PathPair:
    """ Stores a local path (i.e., inside docker)
        alongside its corresponding host path.
    """
    host: Path
    local: Path
