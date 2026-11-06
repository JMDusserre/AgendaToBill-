import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def data_dir():
    override = os.environ.get("AGENDA_DATA_DIR")
    path = Path(override) if override else ROOT / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def invoice_dir():
    override = os.environ.get("AGENDA_INVOICE_DIR")
    return Path(override) if override else ROOT / "factures"


def data_file(name):
    return data_dir() / name


def env_file():
    return ROOT / ".env"
