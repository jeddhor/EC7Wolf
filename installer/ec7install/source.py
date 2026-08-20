"""Getting the engine's source, for an installer that arrived without it.

The installer is published three ways: with binaries, on its own, and inside
the source tree. On its own it is a few hundred kilobytes that can fetch and
build everything -- which is only true if it can fetch the engine's source
too, and that is what this does.

It asks GitHub for the source archive attached to the matching release, and
falls back to the repository's own tarball for a branch. Either way what comes
back is checked for the one file that decides whether it can be built at all.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from . import thirdparty
from .progress import Reporter
from .thirdparty import BuildFailed

REPOSITORY = "jeddhor/EC7Wolf"
FALLBACK_REF = "main"


def _release_source_url(version: str) -> str | None:
    """The source archive attached to the release for this version, if any."""
    url = f"https://api.github.com/repos/{REPOSITORY}/releases/tags/v{version}"
    try:
        request = urllib.request.Request(
            url, headers={"Accept": "application/vnd.github+json",
                          "User-Agent": "ec7wolf-installer"})
        with urllib.request.urlopen(request, timeout=60) as response:
            release = json.load(response)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.endswith("-source.tar.gz"):
            return asset.get("browser_download_url")
    return release.get("tarball_url")


def ensure(cache: Path, reporter: Reporter, version: str | None = None,
           ref: str = FALLBACK_REF) -> Path:
    """A source tree to build, downloading one if necessary."""
    cache.mkdir(parents=True, exist_ok=True)

    existing = thirdparty._find_marker(cache, "CMakeLists.txt")
    if existing is not None:
        reporter.detail(f"source: already downloaded to {existing}")
        return existing

    reporter.step("Downloading the EC7Wolf source", version or ref)
    url = _release_source_url(version) if version else None
    if url is None:
        # No release for this version, or no network to ask: the branch tarball
        # is the same code, just not pinned to a release.
        url = f"https://github.com/{REPOSITORY}/archive/refs/heads/{ref}.tar.gz"
        reporter.detail(f"no release source found; using {ref}")

    archive = thirdparty.download(url, cache / "ec7wolf-source.tar.gz", reporter)
    source = thirdparty.unpack(archive, cache, reporter, "CMakeLists.txt")

    if not (source / "src" / "versiondefs.cmake").is_file():
        raise BuildFailed(
            f"what was downloaded from {url} does not look like the EC7Wolf "
            "source. Download the source package from the releases page and "
            "run the installer from inside it.")
    reporter.detail(f"source: {source}")
    return source
