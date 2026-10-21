---
name: jlcpick
description: Look up LCSC/JLCPCB parts (basic, preferred or extended tier, stock, prices), download their KiCad footprint and STEP, and price a KiCad BOM for JLCPCB assembly with the jlcpick CLI. Use when choosing parts for a board assembled at JLCPCB, checking whether a part is basic or extended, fetching a footprint or 3D model by LCSC code (Cxxxx), or estimating what assembling a board costs and which parts make it expensive.
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
| `lcsc`, `package`, `category`, `mpn`, `manufacturer`, `datasheet` | as JLC lists them |

Cheapest to assemble: basic, then extended with `preferred: true`, then plain extended (a fee
per distinct part).

## Footprint and 3D

```sh
jlcpick get C25744 --out parts
```

Writes `parts/C25744.kicad_mod` and `parts/C25744.step`. The footprint is converted from EasyEDA
and is a draft: tell the user to review it. A missing STEP or missing EasyEDA data is a warning on
stderr, not a failure.

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

The JSON report:

| Field | Meaning |
|---|---|
| `name`, `qty`, `assembly` | board name (file stem), boards, assembly option |
| `fees_as_of`, `fees_source` | date and page of JLC's fee table the fees come from; say it when you quote a cost |
| `sides` | assembled SMT sides (Standard charges setup and stencil per side) |
| `lines` | one per distinct part, costliest first (below) |
| `parts_usd`, `total_usd` | parts for every board; parts plus fees |
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

To make a board cheaper, look at the lines with `feeder_fee: true` and at `charged` well above
`need` (a minimum order): a basic part with the same specs removes both.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | ok, possibly with warnings on stderr |
| 1 | error: unknown code, network down, site blocked us, unexpected answer; for `bom`, a CSV without an LCSC or designator column, a bad code, an `--exclude` designator not in the BOM, a file that is not a KiCad board |
| 2 | invalid usage, e.g. a code that is not `C` + digits |
| 3 | `bom --fail-on-extended` found an extended part paying the feeder fee; the report is printed first |

## Limits

- EasyEDA blocks a client for about 10 minutes after ~25 requests a minute. jlcpick waits 3 s
  between requests to easyeda.com and 2 s to other sites; do not run several jlcpick processes in parallel, and fetch
  `--out` for many parts in one call rather than a loop of calls.
- Prices, stock and tier are live and change over days; do not cache them across sessions.
- `bom` looks up every distinct code once, 2 s apart: about 2 minutes for 60 parts.
- Fees are JLC's published table on `fees_as_of`; JLC may have changed them since. The optional
  "confirm part placement" (0.45) is not included. With `--assembly standard`, packing, fixture and
  the per-board batch fee are not included either.
