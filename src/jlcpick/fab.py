"""JLCPCB's assembly files from the ones KiKit writes: rotation corrections and the parts placed."""

import csv
import io
import re
from collections.abc import Collection, Iterable
from importlib.resources import files

ROTATIONS = files("jlcpick").joinpath("rotations.csv").read_text(encoding="utf-8")


def corrections(footprints: Iterable[str], stock: Collection[str]) -> tuple[str, set[str]]:
    """Return KiKit's correction file for the stock ``footprints``, or "" with nothing to correct,
    and the stock footprints the table lacks.

    ``footprints`` are ``Library:Footprint`` names and ``stock`` the names of KiCad's own
    libraries; footprints of other libraries, converted from EasyEDA or drawn by the team, are
    already in JLC's orientation. The first row of ``rotations.csv`` that matches a footprint is
    its row, as in KiKit, written anchored on that footprint alone.
    """
    rows = list(csv.reader(line for line in ROTATIONS.splitlines() if not line.startswith("#")))
    corrected, unchecked = [], set()
    for name in sorted(set(footprints)):
        if name.partition(":")[0] not in stock:
            continue
        row = next((row for row in rows[1:] if re.match(row[0], name)), None)
        if row is None:
            unchecked.add(name)
        else:
            corrected.append([f"^{re.escape(name)}$", *row[1:]])
    if not corrected:
        return "", unchecked
    out = io.StringIO()
    csv.writer(out, quoting=csv.QUOTE_ALL).writerows([rows[0], *corrected])
    return out.getvalue(), unchecked


def designators(text: str) -> set[str]:
    """Every designator in KiKit's BOM or CPL."""
    return {d for row in csv.DictReader(io.StringIO(text)) for d in row["Designator"].split(",")}


def only(text: str, keep: Collection[str]) -> str:
    """KiKit's BOM or CPL with only the ``keep`` designators, dropping rows left without any."""
    rows = list(csv.reader(io.StringIO(text)))
    column = rows[0].index("Designator")
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(rows[0])
    for row in rows[1:]:
        kept = [d for d in row[column].split(",") if d in keep]
        if kept:
            writer.writerow([*row[:column], ",".join(kept), *row[column + 1 :]])
    return out.getvalue()
