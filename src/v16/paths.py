from __future__ import annotations

from pathlib import Path

from .errors import FailureCode, V16Failure


def project_root(start: Path | None = None) -> Path:
    origin = (start or Path(__file__)).resolve()
    for candidate in (origin, *origin.parents):
        if (candidate / "pyproject.toml").is_file() and \
                (candidate / "docs/specs/v16/SPEC.md").is_file():
            return candidate
    raise V16Failure(FailureCode.PROJECT_ROOT_NOT_FOUND, "required markers absent")


def confined_file(root: Path, requested: str | Path, suffixes: tuple[str, ...]) -> Path:
    raw = Path(requested)
    candidate = (raw if raw.is_absolute() else root / raw).resolve()
    try:
        _ = candidate.relative_to(root.resolve())
    except ValueError:
        raise V16Failure(FailureCode.CONFIG_PATH_OUTSIDE_ROOT, "path escapes project root") from None
    if candidate.suffix.lower() not in suffixes or not candidate.is_file():
        raise V16Failure(FailureCode.CONFIG_NOT_READABLE, "path is not a readable supported file")
    return candidate


def fixture_file(root: Path, relative: str) -> Path:
    base = (root / "docs/specs/v16/fixtures").resolve()
    raw = base / relative
    current = base
    for part in Path(relative).parts:
        current /= part
        if current.is_symlink():
            raise V16Failure(FailureCode.MANIFEST_INVALID, "fixture symlink rejected")
    candidate = raw.resolve()
    try:
        _ = candidate.relative_to(base)
    except ValueError:
        raise V16Failure(FailureCode.MANIFEST_INVALID, "fixture path escapes fixture root") from None
    if not candidate.is_file():
        raise V16Failure(FailureCode.MANIFEST_INVALID, "fixture file missing")
    return candidate
