# c7assets.py — Corridor 7 asset browser

A single-file, standard-library-only web viewer for the Corridor 7 assets. It
decodes everything **into memory** (no files are extracted, no originals are
modified) and serves a categorized, clickable gallery — walls, sprites,
pictures, and maps — with a drill-down metadata view per asset.

## Requirement: run it *in* the Corridor 7 data directory

**`c7assets.py` must be placed in (or pointed at) a directory that holds the
released Corridor 7 game files** — `GFXTILES.CO7`, the `VGAGRAPH`/`VGAHEAD`/
`VGADICT` set, `MAPTEMP.CO7`, `CORR7CD.EXE`, and `ecwolf.pk3`. Those commercial
data files are **not** committed to this repository, so copy this script next to
your own legally-owned Corridor 7 installation (for example the packaged
`builds/release/` directory produced by `package_corridor7_release.sh`).

## Usage

```sh
# from within the data directory:
python3 c7assets.py                     # serves http://127.0.0.1:8777

# or point it at the data directory explicitly, and/or pick a port:
python3 c7assets.py --dir /path/to/release --port 8080
```

Startup decodes the full asset set (~1200 assets) before serving, which takes a
few seconds; once it prints `Serving the Corridor 7 asset browser at ...` open
the URL in a browser. Requires only the Python 3.10+ standard library.
