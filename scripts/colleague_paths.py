"""Shared paths for the current complete colleague deployment release."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAG = '20261008-colleague-02'
OUT = ROOT / 'work/records/colleague-release-20261008-02'
BUILD = ROOT / 'work/records/colleague-build-20261008-02'
ARCHIVE = ROOT / 'work/records/A4S-full-demo-20261008-02.zip'
