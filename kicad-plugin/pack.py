"""Write the archive KiCad's Plugin and Content Manager installs with "Install from File..."."""

import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).parent


def pack(archive: Path) -> None:
    """Write ``archive`` with ``metadata.json`` and the plugin's files under ``plugins/``."""
    files = [HERE / "metadata.json", *sorted((HERE / "plugins").glob("*.*"))]
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for path in files:
            zipped.write(path, path.relative_to(HERE).as_posix())


if __name__ == "__main__":
    pack(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("jlcpick-kicad.zip"))
