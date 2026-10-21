# jlcpick

Command-line tool and Python library for people who design in KiCad and assemble at JLCPCB: look up
a part's tier, price and stock, audit a board's BOM cost and safe basic swaps, add parts to the
project library, and generate the JLCPCB fabrication files.

## Quickstart

```sh
uvx --from . jlcpick get C25744                 # tier, stock, prices, package, datasheet
uvx --from . jlcpick get C25744 C8734 --json    # the same as JSON
uvx --from . jlcpick get C25744 --out parts     # also parts/C25744.kicad_mod and .step
```

jlcpick is not on PyPI yet, so these run from a clone (`--from .`). Once it is published they
become `uvx jlcpick get C25744`.

Footprints are converted from EasyEDA and are drafts: review them before use. EasyEDA data is
cached in `.jlcpick/cache/`; prices, stock and tier are always fetched live. EasyEDA blocks a
client for about 10 minutes after ~25 requests a minute, so jlcpick waits 3 s between requests to
the same site.

## Credits

Footprint and 3D conversion by [easyeda2kicad](https://github.com/uPesy/easyeda2kicad.py)
(AGPL-3.0).

Licensed under the [GNU Affero General Public License v3.0 or later](LICENSE).
