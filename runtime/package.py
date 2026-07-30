#!/usr/bin/env python3
"""Create a byte-reproducible gzip tar archive."""

from __future__ import annotations

import gzip
import sys
import tarfile
from pathlib import Path


def main() -> None:
    source, destination = map(Path, sys.argv[1:3])
    with destination.open("wb") as output, gzip.GzipFile(
        filename="", mode="wb", fileobj=output, mtime=0
    ) as compressed, tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source)
            info = archive.gettarinfo(path, arcname=str(relative))
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            if info.isfile():
                with path.open("rb") as content:
                    archive.addfile(info, content)
            else:
                archive.addfile(info)


if __name__ == "__main__":
    main()
