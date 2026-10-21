---
name: jlcpick
description: Look up LCSC/JLCPCB parts (basic, preferred or extended tier, stock, prices) and download their KiCad footprint and STEP with the jlcpick CLI. Use when choosing parts for a board assembled at JLCPCB, checking whether a part is basic or extended, or fetching a footprint or 3D model by LCSC code (Cxxxx).
---

# jlcpick

Run it with `uvx jlcpick …` (from a clone: `uvx --from <repo> jlcpick …`). Always pass `--json`
when you read the output yourself.

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

## Exit codes

| Code | Meaning |
|---|---|
| 0 | ok, possibly with warnings on stderr |
| 1 | error: unknown code, network down, site blocked us, unexpected answer |
| 2 | invalid usage, e.g. a code that is not `C` + digits |

## Limits

- EasyEDA blocks a client for about 10 minutes after ~25 requests a minute. jlcpick waits 3 s
  between requests to the same site; do not run several jlcpick processes in parallel, and fetch
  `--out` for many parts in one call rather than a loop of calls.
- Prices, stock and tier are live and change over days; do not cache them across sessions.
