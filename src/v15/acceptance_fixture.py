from __future__ import annotations

from pathlib import Path

from .fixtures import ROOT
from .operation_models import OperationBundle
from .operation_verify import verify_operation_bundle


BUNDLE_PATH = ROOT / "docs/specs/v15/fixtures/operation-bundle.json"
SOURCE_PATH = ROOT / "docs/specs/v15/fixtures/operation-source.json"


def load_verified_bundle(path: Path = BUNDLE_PATH) -> OperationBundle:
    return verify_operation_bundle(path.read_bytes())
