import os
from pathlib import Path


def resolve_data_dir(*, frozen: bool, executable: Path, source_dir: Path) -> Path:
    configured = os.environ.get("CERTMON_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if frozen:
        program_data = Path(os.environ.get("PROGRAMDATA", executable.parent))
        return program_data / "CertMon"
    return source_dir / "data"
