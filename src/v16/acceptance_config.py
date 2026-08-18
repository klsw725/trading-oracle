from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from .canonical import canonical_hash
from .config import load_config
from .errors import FailureCode, V16Failure
from .identity import build_identity, config_value
from .models import IdentityRequest, InputManifest, MarketScope
from .paths import confined_file, project_root
from .reporting import EvidenceItem, item


def _config_code(text: str) -> str:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "case.yaml"
        _ = path.write_text(text, encoding="utf-8")
        try:
            _ = load_config(path)
            return "UNEXPECTED_PASS"
        except V16Failure as error:
            return error.code.value


def config_checks(root: Path, config_hash: str) -> list[EvidenceItem]:
    path = root / "docs/specs/v16/fixtures/runtime-config.yaml"
    source = path.read_text(encoding="utf-8")
    cases = (
        ("yaml_duplicate_rejected", source + "policy_version: v16.policy.1\n"),
        ("yaml_tag_rejected", source.replace("mode: paper", "mode: !!binary cGFwZXI=")),
        ("yaml_non_finite_rejected", source.replace("KR: 10", "KR: .nan")),
        ("config_market_identity_rejected", source.replace("currency: KRW", "currency: USD", 1)),
    )
    results = [item(case_id, FailureCode.CONFIG_PARSE_ERROR.value, _config_code(text))
               for case_id, text in cases]
    observed_hash = canonical_hash(config_value(load_config(path)))
    manifest_source = (root / "docs/specs/v16/fixtures/input-manifest.json").read_text(
        encoding="utf-8")
    numeric = manifest_source.replace('"expected_interval_minutes":5',
                                      '"expected_interval_minutes":true', 1)
    try:
        _ = InputManifest.model_validate_json(numeric)
        numeric_code = "UNEXPECTED_PASS"
    except ValidationError:
        numeric_code = "MANIFEST_INVALID"
    config_code = _config_code(source.replace("KR: 10", "KR: true"))
    results.append(item("yaml_bool_integer_rejected",
                        "CONFIG_PARSE_ERROR|MANIFEST_INVALID",
                        f"{config_code}|{numeric_code}"))
    results.append(item("config_identity", config_hash, observed_hash))
    return results


def config_mutations(root: Path, manifest_hash: str) -> list[EvidenceItem]:
    path = root / "docs/specs/v16/fixtures/runtime-config.yaml"
    source = path.read_text(encoding="utf-8")
    config = load_config(path)
    identity = build_identity(IdentityRequest(root=root, config=config,
        manifest_hash=manifest_hash, scope=MarketScope.ALL))
    arm_config = config.model_copy(update={"runtime": config.runtime.model_copy(
        update={"arm_selector": "candidate"})})
    account_config = config.model_copy(update={"runtime": config.runtime.model_copy(
        update={"account_selector": "fixture-account-2"})})
    arm_changed = build_identity(IdentityRequest(root=root, config=arm_config,
        manifest_hash=manifest_hash, scope=MarketScope.ALL))
    account_changed = build_identity(IdentityRequest(root=root, config=account_config,
        manifest_hash=manifest_hash, scope=MarketScope.ALL))
    lines = source.splitlines()
    cosmetic = "\n".join(("# cosmetic reorder", lines[1], lines[0], *lines[2:])) + "\n"
    with TemporaryDirectory() as directory:
        cosmetic_path = Path(directory) / "cosmetic.yaml"
        _ = cosmetic_path.write_text(cosmetic, encoding="utf-8")
        cosmetic_hash = canonical_hash(config_value(load_config(cosmetic_path)))
    original_cwd = Path.cwd()
    with TemporaryDirectory() as directory:
        try:
            os.chdir(directory)
            cwd_root = project_root()
        finally:
            os.chdir(original_cwd)
    try:
        _ = confined_file(root, root.parent / "escape.yaml", (".yaml", ".yml"))
        escape = "UNEXPECTED_PASS"
    except V16Failure as error:
        escape = error.code.value
    unknown = _config_code(source + "unknown_key: redacted\n")
    schema = _config_code(source.replace("v16.runtime-config.1", "v16.runtime-config.unknown"))
    policy = _config_code(source.replace("v16.policy.1", "v16.policy.unknown"))
    return [item("config_escape", FailureCode.CONFIG_PATH_OUTSIDE_ROOT.value, escape),
            item("cosmetic_config_change", identity.config_hash, cosmetic_hash),
            item("cwd_independence", "SAME_ROOT", "SAME_ROOT" if cwd_root == root else "DIFFERENT_ROOT"),
            item("semantic_config_change", "ACCOUNT_CHANGED|ARM_CHANGED",
                 "ACCOUNT_CHANGED|ARM_CHANGED" if
                 account_changed.runtime_identity != identity.runtime_identity and
                 arm_changed.runtime_identity != identity.runtime_identity else "NOT_SEPARATED"),
            item("unknown_config_policy",
                 "UNKNOWN_CONFIG_KEY|UNSUPPORTED_CONFIG_SCHEMA|UNKNOWN_POLICY_VERSION",
                 f"{unknown}|{schema}|{policy}")]
