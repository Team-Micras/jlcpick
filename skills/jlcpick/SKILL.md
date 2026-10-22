---
name: jlcpick
description: Look up LCSC/JLCPCB parts (basic, preferred or extended tier, stock, prices), download their KiCad footprint and STEP, add parts to a KiCad project's library (KiCad's own symbols and footprints when they fit, otherwise a draft converted from EasyEDA), price a KiCad BOM for JLCPCB assembly with safe basic swaps, quote the whole order with the bare boards, and write JLCPCB's Gerbers, BOM and CPL, with the jlcpick CLI. Use when choosing parts for a board assembled at JLCPCB, checking whether a part is basic or extended, fetching a footprint or 3D model by LCSC code (Cxxxx), putting a part with its MPN and LCSC code into a KiCad project, estimating what assembling a board costs and which parts make it expensive, quoting a whole order with the bare boards, or preparing the files of a JLCPCB order.
---

# jlcpick

jlcpick is not on PyPI yet: run it with `uvx --from <path to the clone or git+https://…> jlcpick …`.
After it is published, `uvx jlcpick …` works. Always pass `--json` when you read the output yourself.

## Look up parts

```sh
jlcpick get C25744 C8734 --json
```

Prints a JSON list, one object per code, in the order given:

| Field | Meaning |
|---|---|
| `tier` | `basic` or `extended` |
| `preferred` | `true` for extended parts JLC treats as preferred: no feeder fee in Economic assembly |
| `stock` | units in stock now |
| `prices` | `[{from_qty, usd}]`, unit price from that quantity up |
| `min_qty`, `loss_qty` | for non-basic parts JLC charges `max(need + loss_qty, min_qty)` units |
| `params` | JLC's own attributes, e.g. `Resistance`, `Voltage Rating` |
| `lcsc`, `package`, `category`, `mpn`, `manufacturer`, `datasheet`, `description` | as JLC lists them |

Cheapest to assemble: basic, then extended with `preferred: true`, then plain extended (a fee
per distinct part).

## Footprint and 3D

```sh
jlcpick get C25744 --out parts
```

Writes `parts/C25744.kicad_mod` and `parts/C25744.step`. The footprint is converted from EasyEDA
and is a draft: tell the user to review it. A missing or unreadable STEP, or missing EasyEDA data,
is a warning on stderr, not a failure; without a STEP the footprint is saved without 3D.

## Add parts to the project library

Run it in the KiCad project's folder, next to its `.kicad_pro`:

```sh
jlcpick add C25744 C20917 C2988369 --json
```

Each part becomes a symbol in `lib/<project>.kicad_sym`, registered in the project's
`sym-lib-table`, with `MPN`, `LCSC`, `Manufacturer`, `Datasheet`, `Description` and `Value`.
Its name follows the team's: `Resistor 10kΩ 0402 - 0402WGF1002TCE`, `MOSFETs SOT-23 - AO3400A`.
jlcpick takes the first of these that fits the part:

1. **KiCad's own symbol and footprint for the package**, for chip resistors, MLCCs, SMD
   electrolytics, SMD inductors, LEDs, diodes (switching, general purpose, fast, Schottky, Zener)
   and resettable fuses in the packages listed in `packages.toml` (0402 to 2512, SOD-123, SOD-323,
   SMA, SMB, SMC…). The symbol extends KiCad's base symbol (`Device:R`, `Device:C`…, copied into
   the library once) and points at KiCad's footprint, e.g. `Resistor_SMD:R_0402_1005Metric`.
   `Value` is `10kΩ`, `100nF`, the LED color, or the MPN.
2. **KiCad's own symbol named after the MPN**, when KiCad 10 has one with a footprint, e.g.
   `Transistor_FET:AO3400A`, `Regulator_Linear:AMS1117-3.3`. The symbol extends the KiCad symbol
   that one extends (`Q_NMOS_GSD`, copied once) and keeps its footprint
   (`Package_TO_SOT_SMD:SOT-23`), keywords and pins. The name must match exactly:
   `STM32H725RGV6` does not match KiCad's `STM32H725RGVx`.
3. **A draft converted from EasyEDA**, for everything else (ICs, connectors…): symbol, footprint
   and STEP. The footprint goes to `lib/<project>.pretty/<EasyEDA package>.kicad_mod`, registered
   in the project's `fp-lib-table`; the STEP to `lib/<project>.3dshapes/`, referenced from the
   footprint as `${KIPRJMOD}/lib/<project>.3dshapes/…`. jlcpick places the STEP where EasyEDA
   does; easyeda2kicad alone leaves it 1.05 mm off on the USB-C C2988369. The output marks the
   part `draft: review footprint and 3D`: tell the user to check pads, silkscreen, courtyard and 3D before ordering.
   Parts with the same EasyEDA package share one footprint. KiCad reformats a converted symbol
   when it saves the library, so a later `add` of that part says `kept`.

| Flag | Meaning |
|---|---|
| `--lib DIR` | folder of the library, default `lib` |
| `--force` | replace a symbol of the same name that differs, and a footprint or STEP of the same name that differs unless another symbol of the library uses it; without it the library's version is kept and a warning says so |
| `--json` | print JSON |

The JSON is a list, one object per code:

| Field | Meaning |
|---|---|
| `lcsc` | the code |
| `symbol`, `footprint` | the symbol's name in the library and its footprint (`<project>:<name>` for a draft) |
| `status` | `added`; `unchanged`, already there as is; `replaced`, with `--force`; `kept`, a different symbol of that name stays |
| `draft` | `true` when converted from EasyEDA: review its footprint and 3D |

Running `add` again changes no byte. jlcpick finds KiCad 10's libraries where KiCad installs them
(also Flatpak); otherwise set `KICAD10_SYMBOL_DIR` and `KICAD10_FOOTPRINT_DIR`.

Warnings (stderr, exit 0):

- `CODE: <library> already has a different "<symbol>", kept`: someone edited the symbol; `--force`
  replaces it with jlcpick's version.
- `CODE: kept <file>, it differs from the EasyEDA conversion`: someone edited the footprint or
  STEP, or another part of the same package made it differently. The symbol is written anyway,
  pointing at that file. `--force` rewrites the file; when the warning ends `<symbols> also use
  it`, `--force` refuses, see below.
- `sym-lib-table maps <project> to <uri>, but add wrote <uri>` (or `fp-lib-table`): the table
  points the project's library at another file; fix the table, jlcpick leaves it as is.
- `CODE: EasyEDA has no STEP model`: the draft has a footprint without 3D.

Errors (exit 1, nothing written):

- `CODE (package, category): no KiCad symbol or footprint fits it and EasyEDA has nothing to
  convert`: draw the part by hand.
- `<library> already has a <base> wired differently from KiCad's`: a base symbol in the library
  (`D`, `Q_NMOS_GSD`…) has other pin numbers than KiCad's; restore it from KiCad's library.
- `CODE1 and CODE2 both make the symbol "<name>"` (same MPN under two codes): add only the one
  you want. `both make <file>, differently` (two EasyEDA footprints with one name): add only one;
  the other would get that footprint, so draw it by hand.
- `CODE: --force would rewrite <file>, which <symbols> also use`: rewriting it would change
  those symbols' footprint too. Delete the file to have `add` write it again for all of them, or
  leave it as is.
- `<library>: empty or cut off, its parentheses do not balance`: the library or a table is
  damaged; restore it from git.
- `CODE: EasyEDA's footprint has no pad for pin N of its symbol`: EasyEDA's data is wrong.
- `CODE: <file> has no pad for pin N of its symbol`: the footprint kept in the library, edited
  or made by another part of the same package, does not fit this part; draw this part's
  footprint by hand.
- `<footprint> has no pad for pin N of <symbol>; fix packages.toml`: a bug in jlcpick's tables.
  Without `; fix packages.toml`, it is KiCad's own symbol for the MPN that lacks the pad.

## Price a BOM

Export the BOM from the schematic, then price it with the board:

```sh
kicad-cli sch export bom board.kicad_sch -o bom.csv --ref-range-delimiter '' \
  --fields 'Reference,Value,Footprint,QUANTITY,DNP,LCSC' \
  --labels 'Refs,Value,Footprint,Qty,DNP,LCSC' --group-by 'Value,Footprint,LCSC,DNP'
jlcpick bom bom.csv --pcb board.kicad_pcb --qty 5 --json
```

`LCSC` in `--fields` is the symbol field with the code; if the project names it differently
(`SUPPLIER PART`, `LCSC Part #`…), put that name in `--fields` and keep the `LCSC` label. Columns
named `LCSC Part`, `JLCPCB Part #` or `Supplier Part`, and `Designator`/`Comment` (Altium) are also
read. A one-column CSV of codes works too, one use per row.

| Flag | Meaning |
|---|---|
| `--pcb` | the `.kicad_pcb`: joints, sides and through-hole parts. Without it joints are `null` and one side is assumed (a warning says so) |
| `--qty` | boards to assemble, default 5 |
| `--assembly` | `economic` (default) or `standard` |
| `--exclude U1,U3` | leave these designators out of the order, as if DNP. DNP rows are always left out |
| `--fail-on-extended` | exit 3 when an extended part pays the feeder fee: Economic, extended and not preferred; Standard, any extended part (preferred included) |
| `--verbose` | in the text report, also list the parts no swap replaces, with the reason |
| `--no-swaps` | skip the search for safe swaps: one or two searches per extended part, 72 s of 226 s on a board with 27 |

The JSON report:

| Field | Meaning |
|---|---|
| `name`, `qty`, `assembly` | board name (file stem), boards, assembly option |
| `fees_as_of`, `fees_source` | date and page of JLC's fee table the fees come from; say it when you quote a cost |
| `sides` | assembled SMT sides (Standard charges setup and stencil per side) |
| `lines` | one per distinct part, costliest first (below) |
| `parts_usd`, `total_usd` | parts for every board; parts plus fees |
| `saves_usd` | what all the safe swaps save together; `null` with `--no-swaps` |
| `fees` | the order's fees (below) |
| `warnings` | rows without a code, designators missing from the board, no `--pcb` |

Each of `lines`:

| Field | Meaning |
|---|---|
| `lcsc`, `designators`, `mpn`, `tier`, `preferred` | the part and where it goes |
| `need` | units placed: uses per board × `qty` |
| `charged` | units JLC bills: `need` for basic, otherwise `max(need + loss_qty, min_qty)` |
| `unit_usd`, `total_usd` | price at the break `charged` reaches, and `charged × unit_usd` |
| `feeder_fee` | the part pays the feeder fee (`fees.feeder_each_usd`) |
| `tht`, `joints` | hand-soldered or not, solder joints on all boards; `null` without `--pcb` |
| `swap` | what to do with the part (below); `null` with `--no-swaps` |

Each `swap`:

| Field | Meaning |
|---|---|
| `verdict` | `swap`: a basic or preferred part replaces it and no field gets worse; `to_check`: a person must decide; `no_rule`: jlcpick has no rule for this kind of part; `keep`: already basic or preferred, or no candidate is as good, in stock or cheaper (a search JLC cut at 50 results says so) |
| `reason` | for `swap`, `same MPN` or the attributes matched (`18pF 50V C0G ±5% 0402`); otherwise why, e.g. `C45783: voltage 25V vs 35V`, `shunt below 1 Ω` |
| `to` | the replacement, only when `verdict` is `swap`; otherwise `null` |

`to` has `lcsc`, `mpn`, `tier` and `preferred` of the replacement, and `saves_usd`: the feeder fee
avoided plus the difference in parts and attrition at this `qty`. With several safe candidates it
is the one that saves most.

A swap is safe when the replacement is basic or preferred, has enough stock for the order, saves
money, and either has the same MPN, package and maker (the same MPN from another maker is
`to_check`) or, for resistors and capacitors, is in the same JLC category and package, with the same value and
equal or better voltage or power, tolerance, temperature coefficient (resistors) and dielectric
(C0G = NP0 > X7R > X5R > Y5V). Electrolytic and polymer capacitors, shunts below 1 Ω, other
dielectrics (X7S, X6S…) and attributes JLC leaves blank are `to_check`. ICs, connectors, LEDs,
inductors, switches, fuses and everything else that is not a resistor or capacitor are `no_rule`
unless the same MPN exists as basic or preferred.

`fees`, each in US$ rounded to the cent:

| Field | Meaning |
|---|---|
| `setup_usd`, `stencil_usd` | per order; per side in Standard |
| `feeder_parts`, `feeder_each_usd`, `feeder_usd` | parts paying the feeder fee: Economic, extended SMT parts that are not preferred; Standard, every SMT part |
| `smt_joints`, `smt_joints_usd` | machine-placed joints |
| `manual_joints`, `manual_usd` | hand-soldered (THT) joints, plus the per-order labor fee |
| `xray_units`, `xray_each_usd`, `xray_usd` | X-ray inspection, both assemblies: SMT units of leadless packages (BGA, QFN, DFN, LGA, WLCSP and variants), priced by the band their total reaches |
| `handling_usd` | Standard only: what is missing for Standard to cost 14.93 more than Economic |
| `total_usd` | all the fees |

To make a board cheaper, apply the lines whose `swap.verdict` is `swap`; then look at the
`to_check` ones and the lines with `feeder_fee: true` and at `charged` well above `need` (a
minimum order): a basic part with the same specs removes both.

## Quote a whole order

```sh
jlcpick quote bom.csv --pcb board.kicad_pcb --qty 5 --json
```

Prices the bare boards with JLC's own order calculator, live, and adds the assembly that `bom`
prices (same BOM, `--assembly` and `--exclude`; no swap search, run `bom` for that). The board's
size is the bounding box of its Edge.Cuts drawings (not those inside footprints), its layers are
the copper layers of the file, and its thickness is the file's, rounded to JLC's nearest option
(0.4, 0.6, 0.8, 1.0, 1.2, 1.6 or 2.0 mm). Everything else is JLC's default: HASL with lead, 1 oz
copper, white silkscreen (black on a white mask). `--color` picks the solder mask: `green`
(default), `purple`, `red`, `yellow`, `blue`, `white` or `black`; colors other than green cost
more. Shipping, taxes and customs are not included.

The JSON:

| Field | Meaning |
|---|---|
| `name`, `qty` | board name (file stem), boards made and assembled |
| `board` | the bare boards (below) |
| `pcba` | the assembly, the same report as `bom --json --no-swaps` |
| `extended` | what the extended parts add (below) |
| `total_usd` | `board.usd` plus `pcba.total_usd` |

`board`:

| Field | Meaning |
|---|---|
| `width_mm`, `length_mm`, `layers` | as read from the file |
| `thickness_mm`, `kicad_thickness_mm` | JLC's option priced, and the file's own thickness |
| `color` | solder mask |
| `usd`, `build_time` | JLC's price for all the boards and its build time, e.g. `3-4 days` |

`extended`, in US$ unless said:

| Field | Meaning |
|---|---|
| `parts` | extended lines, preferred included |
| `feeder_usd` | feeder fees of extended parts; 0 in Standard, where basic parts pay it too |
| `extra_units_usd` | units JLC charges beyond those placed: attrition and minimums |
| `usd`, `share_pct` | their sum, and its percentage of `total_usd` |

## Fabrication files

```sh
jlcpick fab board.kicad_pcb --exclude U1 --out jlcpcb
```

Writes what JLCPCB's order page asks for: `jlcpcb/gerbers.zip`, `jlcpcb/bom.csv` and
`jlcpcb/pos.csv` (the CPL), by running KiKit's `kikit fab jlcpcb`. It needs the board's
`.kicad_sch` next to it, with the LCSC code in a symbol field named like a BOM's LCSC column
(`LCSC`, `LCSC Part #`, `SUPPLIER PART`…). DNP parts, parts without a code (a warning lists them)
and `--exclude` designators stay out of both the BOM and the CPL, as in `bom`. KiKit's DRC is
skipped: run it in KiCad.

Rotations: footprints from KiCad's own libraries get the corrections of
[JLCKicadTools](https://github.com/matthewlai/JLCKicadTools) (`src/jlcpick/rotations.csv`). The
project's footprints get none: those converted from EasyEDA are assumed to be in JLC's
orientation, as EasyEDA draws them, and those the team drew to KiCad's standard are not
corrected, so check them in JLC's preview. Positions are the footprint's origin.

`fab` needs KiKit and KiCad's Python (`pcbnew`): install `jlcpick[fab]` in a Python that imports
`pcbnew` (a venv made with `--system-site-packages` from KiCad's Python), or run it in Docker as
the README shows. Without them `fab` says so and exits 1; the other commands do not need them.

Problems (stderr, exit 3, after the files are written):

- `no checked rotation for KiCad's footprint, check it in JLC's preview: D1 (LED_SMD:…)`: the
  table has no row for that stock footprint; check the part in JLC's preview before ordering.
- `KiCad's through-hole footprint is placed by its pin 1, check its position in JLC's preview:
  …`: the CPL gives the footprint's origin, which is pin 1 there, not the part's center.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | ok, possibly with warnings on stderr |
| 1 | error: unknown code, network down, site blocked us, unexpected answer; for `bom`, a CSV without an LCSC or designator column, a bad code, an `--exclude` designator not in the BOM, a file that is not a KiCad board; for `quote`, also a board without an Edge.Cuts outline or thickness, or JLC's calculator failing; for `fab`, no schematic next to the board, no LCSC field in it, an `--exclude` designator not on the board, KiKit missing or failing, or KiCad 10's footprints not found (set `KICAD10_FOOTPRINT_DIR`); for `add`, a part neither KiCad nor EasyEDA has, no `.kicad_pro` in the folder, KiCad 10 not found, or the cases listed under "Add parts" |
| 2 | invalid usage, e.g. a code that is not `C` + digits |
| 3 | `bom --fail-on-extended` found an extended part paying the feeder fee; the report is printed first. `fab`: a stock footprint without a checked rotation, or a stock through-hole one; the files are written first |

## Limits

- EasyEDA blocks a client for about 10 minutes after ~25 requests a minute. jlcpick waits 3 s
  between requests to easyeda.com and 2 s to other sites; do not run several jlcpick processes in parallel, and fetch
  `--out` for many parts in one call rather than a loop of calls.
- Prices, stock and tier are live and change over days; do not cache them across sessions.
- `bom` looks up every distinct code once, 2 s apart: about 2 minutes for 60 parts, plus one or
  two searches per extended part for swaps (the MainBoard, 64 parts and 27 extended, took 226 s;
  154 s with `--no-swaps`).
- `quote` makes one request to JLC's calculator, then looks up the parts as `bom --no-swaps` does.
  The board price is live; say the date when you pass it on.
- Fees are JLC's published table on `fees_as_of`; JLC may have changed them since. The optional
  "confirm part placement" (0.45) is not included. With `--assembly standard`, packing, fixture and
  the per-board batch fee are not included either.
