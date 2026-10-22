# jlcpick: notes for agents working on this repo

To *use* jlcpick, read [skills/jlcpick/SKILL.md](skills/jlcpick/SKILL.md).

## Check before every commit

```sh
uv run ruff check && uv run ruff format --check && uv run ty check && uv run pytest
```

`uv run pytest -m live` hits the real sites; run it rarely (see the rate limit below).
`JLCPICK_MAINBOARD=<folder with MicrasMainBoard.kicad_pcb and its sheets> uv run pytest -m kicad`
runs the real KiKit; it needs `jlcpick[fab]` in a Python that imports `pcbnew`, such as the
`kicad/kicad:10.0.7` image (README).

## Rules

- Only `src/jlcpick/sources/` touches the network. Everything else is pure; `cli.py` coordinates;
  only `cli.py` and the EasyEDA cache in `sources/` write files.
- `kicad-plugin/` is KiCad 10's plugin: it runs the CLI on the open board and shows its output,
  with no logic of its own beyond building the commands; `tests/test_kicad_plugin.py` tests that
  without KiCad.
- Tests go through the CLI with recorded fixtures in `tests/fixtures/`. To record new ones, fetch
  part by part with a pause: EasyEDA blocks for ~10 minutes after ~25 requests a minute.
- No comments inside function bodies; docstrings on public functions.
- A slice that adds or changes a command also updates `skills/jlcpick/SKILL.md` and the README.
- Commits: gitmoji + one short English sentence, one line. Never push without the owner's ok.
