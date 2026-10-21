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

Price a board's assembly from its KiCad BOM:

```sh
kicad-cli sch export bom board.kicad_sch -o bom.csv --ref-range-delimiter '' \
  --fields 'Reference,Value,Footprint,QUANTITY,DNP,LCSC' \
  --labels 'Refs,Value,Footprint,Qty,DNP,LCSC' --group-by 'Value,Footprint,LCSC,DNP'
uvx --from . jlcpick bom bom.csv --pcb board.kicad_pcb --qty 5
```

`LCSC` is the symbol field holding the code; use your field's name in `--fields`. The report
lists parts, fees (setup, stencil, extended-part feeder, X-ray of leadless parts, joints) and every part that
is not basic,
with the units JLC charges after attrition and minimums, then the safe swaps: basic or preferred
parts with the same MPN, or resistors and capacitors with the same value and package and no worse
field, with what each saves. Parts it cannot judge are counted as "to check" or "no rule";
`--verbose` lists them with the reason, and `--no-swaps` skips the search. See
[docs/example-bom.txt](docs/example-bom.txt). `--exclude U1,U3` leaves parts out of the order,
`--assembly standard` prices Standard PCBA (packing, fixture and the per-board batch fee are not
included), `--json` prints JSON, and `--fail-on-extended` exits 3 when an extended part pays the
feeder fee. Fees come from JLC's
[PCB Assembly Price](https://jlcpcb.com/help/article/pcb-assembly-price) page of 2026-09-09, and
every report prints that date.

jlcpick is not on PyPI yet, so these run from a clone (`--from .`). Once it is published they
become `uvx jlcpick get C25744`.

Footprints are converted from EasyEDA and are drafts: review them before use. EasyEDA data is
cached in `.jlcpick/cache/`; prices, stock and tier are always fetched live. EasyEDA blocks a
client for about 10 minutes after ~25 requests a minute, so jlcpick waits 3 s between requests to
easyeda.com and 2 s to other sites.

## For agents

[skills/jlcpick/SKILL.md](skills/jlcpick/SKILL.md) teaches an agent to use jlcpick; copy it
into your agent's skills folder. [AGENTS.md](AGENTS.md) is for agents working on this repo.

## Credits

The pricing scenarios in the tests come from
[Bouni/kicad-jlcpcb-tools](https://github.com/Bouni/kicad-jlcpcb-tools) (MIT), recalculated at
today's fees.

Footprint and 3D conversion by [easyeda2kicad](https://github.com/uPesy/easyeda2kicad.py)
(AGPL-3.0).

Licensed under the [GNU Affero General Public License v3.0 or later](LICENSE).
