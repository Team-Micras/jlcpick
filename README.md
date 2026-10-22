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

Without cloning, until jlcpick is on PyPI:

```sh
uvx --from git+https://github.com/Team-Micras/jlcpick@v0.2.0 jlcpick get C25744
uv tool install git+https://github.com/Team-Micras/jlcpick@v0.2.0      # jlcpick on PATH
uv add --dev git+https://github.com/Team-Micras/jlcpick@v0.2.0         # in a project's own tools
```

Add parts to a KiCad project's library, from the project's folder:

```sh
uvx --from /path/to/jlcpick jlcpick add C25744 C20917 C2988369   # lib/<project>.kicad_sym + sym-lib-table
```

Each part gets a symbol named like `Resistor 10kΩ 0402 - 0402WGF1002TCE`, with its MPN, LCSC code,
manufacturer, datasheet and description:

- resistors, capacitors, inductors, LEDs, diodes and resettable fuses in standard packages extend
  KiCad's own `Device:R`… and use KiCad's own footprint for the package, listed in
  [src/jlcpick/packages.toml](src/jlcpick/packages.toml);
- a part whose MPN names a KiCad symbol, like `Transistor_FET:AO3400A`, extends that symbol and
  keeps its KiCad footprint;
- anything else is converted from EasyEDA as a draft to review: the footprint goes to
  `lib/<project>.pretty` (registered in `fp-lib-table`) and its STEP to `lib/<project>.3dshapes`,
  placed on the pads.

Running it again changes nothing; `--force` replaces a symbol that was edited, and a footprint or STEP that was edited unless another symbol uses it.

Price a board's assembly from its schematic:

```sh
uvx --from . jlcpick bom board.kicad_sch --pcb board.kicad_pcb --qty 5
```

`bom` exports the BOM of the root `.kicad_sch` with KiCad's `kicad-cli`, reading the code from
every symbol field named like `LCSC`, `LCSC Part #` or `SUPPLIER PART` that holds one, the same
fields `fab` reads. It finds `kicad-cli` on PATH, then where KiCad 10 installs it on macOS and
Windows, then in KiCad's Flatpak (`flatpak run --command=kicad-cli org.kicad.KiCad`, which only
sees files under your home); `--kicad-cli PATH` names another. A BOM exported by hand works too:

```sh
kicad-cli sch export bom board.kicad_sch -o bom.csv --ref-range-delimiter '' \
  --fields 'Reference,Value,Footprint,QUANTITY,DNP,LCSC' \
  --labels 'Refs,Value,Footprint,Qty,DNP,LCSC' --group-by 'Value,Footprint,LCSC,DNP'
uvx --from . jlcpick bom bom.csv --pcb board.kicad_pcb --qty 5
```

There `LCSC` is the symbol field holding the code; use your field's name in `--fields`. The report
lists parts, fees (setup, stencil, extended-part feeder, joints) and every part that is not basic,
with the units JLC charges after attrition and minimums, then the safe swaps: basic or preferred
parts with the same MPN, or resistors and capacitors with the same value and package and no worse
field, with what each saves. Parts it cannot judge are counted as "to check" or "no rule";
`--verbose` lists them with the reason, and `--no-swaps` skips the search. See
[docs/example-bom.txt](docs/example-bom.txt). `--exclude U1,U3` leaves parts out of the order,
`--assembly standard` prices Standard PCBA (packing, fixture and the per-board batch fee are not
included), `--json` prints JSON, and `--fail-on-extended` exits 3 when an extended part pays the
feeder fee. Every extended part that is not preferred pays the feeder fee in Economic, through-hole
ones too, as JLC charged on a real order; Standard charges it for every part placed by machine. X-ray of leadless parts (BGA, QFN…) is shown apart, as
"if JLC requires it", and left out of the total: JLC did not charge it on that order. A part with
less stock than the units JLC charges gets a warning. Fees come from JLC's
[PCB Assembly Price](https://jlcpcb.com/help/article/pcb-assembly-price) page of 2026-09-09, and
every report prints that date.

Quote the whole order, bare boards plus assembly:

```sh
uvx --from . jlcpick quote board.kicad_sch --pcb board.kicad_pcb --qty 5
```

`quote` takes the schematic or an exported BOM, as `bom` does. `--qty` is the boards made;
`--assemble 2` assembles only two of them (default: all).

The boards are priced live by JLC's own order calculator, with the size, copper layers and
thickness read from the `.kicad_pcb` (thickness rounded to JLC's nearest option) and JLC's
defaults for the rest; `--color` picks the solder mask. The assembly is the `bom` report without
the swap search, and the quote says how much the extended parts add: their feeder fees and the
units JLC charges beyond those placed. Shipping, taxes and customs are not included. See
[docs/example-quote.txt](docs/example-quote.txt).

Write the files of a JLCPCB order, `jlcpcb/gerbers.zip`, `jlcpcb/bom.csv` and `jlcpcb/pos.csv`:

```sh
jlcpick fab board.kicad_pcb --exclude U1
```

`fab` runs [KiKit](https://github.com/yaqwsx/KiKit)'s `kikit fab jlcpcb` on the board and the
`.kicad_sch` next to it, reading the LCSC code from the symbol field named `LCSC`,
`SUPPLIER PART` or another LCSC column name `bom` reads. Parts marked DNP, without a code, or in
`--exclude` stay out of the BOM and the CPL. Footprints from KiCad's own libraries get the rotation
corrections JLC needs; the project's own footprints and those converted from EasyEDA are already
in JLC's orientation. A stock footprint with no known correction, or a stock through-hole one,
exits 3 after writing the files: check that part in JLC's preview.

KiKit needs KiCad's Python (`pcbnew`), so `fab` runs where both are: install `jlcpick[fab]` in a
venv made with `--system-site-packages` from KiCad's Python, or use KiCad's Docker image from the
board's folder:

```sh
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$(command -v uv)":/usr/local/bin/uv:ro \
  -v /path/to/jlcpick:/jlcpick:ro -v "$PWD":/work -w /work kicad/kicad:10.0.7 sh -c \
  'uv venv -q --system-site-packages --python /usr/bin/python3 /tmp/v &&
   VIRTUAL_ENV=/tmp/v uv pip install -q "/jlcpick[fab]" && /tmp/v/bin/jlcpick fab board.kicad_pcb'
```

jlcpick is not on PyPI yet, so these run from a clone (`--from .`). Once it is published they
become `uvx jlcpick get C25744`.

Footprints are converted from EasyEDA and are drafts: review them before use. EasyEDA data is
cached in `.jlcpick/cache/`; prices, stock and tier are always fetched live. EasyEDA blocks a
client for about 10 minutes after ~25 requests a minute, so jlcpick waits 3 s between requests to
easyeda.com and 2 s to other sites.

## KiCad plugin

The same commands from KiCad 10's PCB editor, as four toolbar buttons that run jlcpick on the open
board and show its report in a window:

- **Audit BOM cost**: `bom` on the board's schematic, exported with KiCad's own `kicad-cli`, with
  the board for joints and sides;
- **Quote JLCPCB order**: `quote` on the same schematic and board;
- **Add part by LCSC code**: `add` the codes typed, in the project's folder;
- **Write JLCPCB files**: `fab` into the project's `jlcpcb` folder.

Audit, Quote and Write save the board first, so they read what the editor shows; when KiCad cannot
save it, they say so and stop. Save the schematic yourself: the plugin reaches only the PCB editor.

To install it:

1. In KiCad, Preferences → Plugins: check "Enable KiCad API".
2. Either run `python kicad-plugin/pack.py` and install the `jlcpick-kicad.zip` it writes with
   Plugin and Content Manager → Install from File…, or copy `kicad-plugin/plugins` into KiCad's
   plugins folder as `jlcpick`: `~/.local/share/kicad/10.0/plugins` on Linux
   (`~/.var/app/org.kicad.KiCad/data/kicad/10.0/plugins` with Flatpak),
   `Documents\KiCad\10.0\plugins` on Windows, `~/Documents/KiCad/10.0/plugins` on macOS.
3. Restart KiCad. It makes a Python environment for the plugin and installs into it the jlcpick
   release the plugin names, tag `v0.2.0` from GitHub (with `git`, a minute or two); the buttons
   appear when that is done. That first start needs the network, and the tag must be published:
   until it is, KiCad never marks the plugin ready.

To update, the release gets a new `version` in `pyproject.toml` and `kicad-plugin/metadata.json`,
the same tag in `kicad-plugin/plugins/requirements.txt`, and that tag on GitHub; install the new
plugin. If the buttons still run the old jlcpick, Preferences → Plugins → Recreate Plugin
Environment. Once jlcpick is on PyPI, the requirement becomes `jlcpick==X.Y.Z` and needs no `git`.

On Linux KiCad runs the plugin with the first `python3` on PATH. With pyenv, conda or uv's Python
first, point Preferences → Plugins → Python interpreter at the system's Python, the one that
imports `wx` and `pcbnew` (`/usr/bin/python3`).

The plugin shows its reports with wxPython, which KiCad's Python has on Windows, macOS and
Flatpak; on Debian and Ubuntu install `python3-wxgtk4.0`. KiCad installs only wheels and some of
KiKit's dependencies have none, so the first Write JLCPCB files installs KiKit into the plugin's
environment itself; it then uses KiCad's own `pcbnew`. Cancel stops jlcpick and what it started.

## For agents

[skills/jlcpick/SKILL.md](skills/jlcpick/SKILL.md) teaches an agent to use jlcpick; copy it
into your agent's skills folder. [AGENTS.md](AGENTS.md) is for agents working on this repo.

## Credits

The pricing scenarios in the tests come from
[Bouni/kicad-jlcpcb-tools](https://github.com/Bouni/kicad-jlcpcb-tools) (MIT), recalculated at
today's fees.

`add` copies base symbols from the [KiCad libraries](https://gitlab.com/kicad/libraries)
(CC-BY-SA 4.0 with an exception for designs that use them); `tests/fixtures/kicad/` holds the
symbols and footprints it uses, from KiCad 10.0.7.

`fab` runs [KiKit](https://github.com/yaqwsx/KiKit) (MIT). Its rotation corrections,
`src/jlcpick/rotations.csv`, are the `cpl_rotations_db.csv` of
[JLCKicadTools](https://github.com/matthewlai/JLCKicadTools) by Matthew Lai and contributors
(GPL-3.0; the text is in `LICENSES/GPL-3.0.txt`). jlcpick translates it to KiKit's format.

Symbol, footprint and 3D conversion by [easyeda2kicad](https://github.com/uPesy/easyeda2kicad.py)
(AGPL-3.0).

Licensed under the [GNU Affero General Public License v3.0 or later](LICENSE).
