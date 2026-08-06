import re
from dataclasses import dataclass
from typing import Final

from src.v4.models import JsonValue, canonical_hash
from .snapshot_validation import CandidateIdentityEvidence, RecommendationInput

_API_KEY_PATTERN: Final = re.compile(r"\b(?:sk|pk|api)[-_][A-Za-z0-9_-]{12,}\b")
_OAUTH_PATTERN: Final = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{12,}")
_FREE_TEXT_PATTERN: Final = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")
_ACCOUNT_PATTERN: Final = re.compile(r"(?<!\d)\d{8,12}(?!\d)")
_LOCAL_PATH_PATTERN: Final = re.compile(
    r"(?:~|/[^\s]*)/(?:\.trading-oracle|\.shacs-bot|\.config)/[^\s]*auth[^\s]*"
)
_MACHINE_ID_KEYS: Final = frozenset(
    {
        "universe_id",
        "source_id",
        "calendar_id",
        "benchmark_id",
        "provider_request_id",
    }
)


def _replacement_for_key(key: str) -> tuple[str, str] | None:
    normalized = key.lower()
    if normalized in {"authorization", "access_token", "refresh_token", "oauth_token"}:
        return "oauth_token", "REDACTED_SECRET(oauth_token)"
    if normalized in {"api_key", "anthropic_api_key", "openai_api_key"}:
        return "api_key", "REDACTED_SECRET(api_key)"
    if normalized in {"client_secret", "broker_secret", "cert_password", "password"}:
        return "broker_secret", "REDACTED_SECRET(broker_secret)"
    if normalized in {
        "account",
        "account_id",
        "account_no",
        "account_number",
        "broker_account",
        "broker_account_id",
        "user_account_id",
    }:
        return "account_id", "REDACTED_ACCOUNT_ID"
    if normalized in {"auth_path", "credential_path", "credentials_path"}:
        return "local_secret_path", "REDACTED_LOCAL_SECRET_PATH"
    return None


def _record_event(
    events: list[JsonValue],
    path: str,
    secret_class: str,
    replacement: str,
) -> None:
    events.append(
        {"field_path": path, "class": secret_class, "replacement": replacement}
    )


def _redact_string(
    value: str,
    key: str | None,
    path: str,
    events: list[JsonValue],
) -> str:
    redacted = value
    patterns = (
        (_LOCAL_PATH_PATTERN, "local_secret_path", "REDACTED_LOCAL_SECRET_PATH"),
        (_OAUTH_PATTERN, "oauth_token", "REDACTED_SECRET(oauth_token)"),
        (_API_KEY_PATTERN, "api_key", "REDACTED_SECRET(api_key)"),
    )
    for pattern, secret_class, replacement in patterns:
        if pattern.search(redacted) is not None:
            redacted = pattern.sub(replacement, redacted)
            _record_event(events, path, secret_class, replacement)
    if not redacted.startswith("sha256:"):
        if _FREE_TEXT_PATTERN.search(redacted) is not None:
            replacement = "REDACTED_SECRET(free_text)"
            redacted = _FREE_TEXT_PATTERN.sub(replacement, redacted)
            _record_event(events, path, "secret_like_free_text", replacement)
        machine_id = key in _MACHINE_ID_KEYS
        if not machine_id and _ACCOUNT_PATTERN.search(redacted) is not None:
            redacted = _ACCOUNT_PATTERN.sub("REDACTED_ACCOUNT_ID", redacted)
            _record_event(events, path, "account_id", "REDACTED_ACCOUNT_ID")
    return redacted


def redact(
    value: JsonValue,
    path: str,
    events: list[JsonValue],
    key: str | None = None,
) -> JsonValue:
    keyed = _replacement_for_key(key) if key is not None else None
    if keyed is not None:
        secret_class, replacement = keyed
        _record_event(events, path, secret_class, replacement)
        return replacement
    match value:  # noqa: MATCH_OK - basedpyright proves JsonValue is exhaustive.
        case None | bool() | int() | float():
            return value
        case str():
            return _redact_string(value, key, path, events)
        case list():
            return [
                redact(item, f"{path}[{index}]", events)
                for index, item in enumerate(value)
            ]
        case dict():
            return {
                item_key: redact(item, f"{path}.{item_key}", events, item_key)
                for item_key, item in value.items()
            }


@dataclass(frozen=True, slots=True)
class PreparedRecommendation:
    source: RecommendationInput
    evidence: CandidateIdentityEvidence
    body: dict[str, JsonValue]
    candidate_universe_hash: str
    prompt_hash: str
    config_hash: str
    parsed_result_hash: str


def prepare_recommendation(
    recommendation: RecommendationInput,
    evidence: CandidateIdentityEvidence,
    index: int,
    events: list[JsonValue],
) -> PreparedRecommendation:
    identity = recommendation.identity
    provenance = recommendation.provenance
    root = f"recommendations[{index}]"
    candidate_universe = redact(
        provenance.candidate_universe, f"{root}.candidate_universe", events
    )
    selection = redact(provenance.selection, f"{root}.selection", events)
    rejections = redact(provenance.rejections, f"{root}.rejections", events)
    prompt_messages = redact(
        provenance.llm.prompt_messages,
        f"{root}.llm.prompt_messages_redacted",
        events,
    )
    config = redact(provenance.llm.config, f"{root}.llm.config", events)
    raw_results = redact(
        provenance.llm.raw_results, f"{root}.llm.raw_results", events
    )
    parsed_results = redact(
        provenance.llm.parsed_results, f"{root}.llm.parsed_results", events
    )
    consensus = redact(provenance.consensus, f"{root}.consensus", events)
    deliberation = redact(
        provenance.deliberation, f"{root}.deliberation", events
    )
    portfolio = redact(
        provenance.portfolio_state, f"{root}.portfolio_state", events
    )
    risk = redact(provenance.risk_state, f"{root}.risk_state", events)
    sources = redact(provenance.sources, f"{root}.sources", events)
    features = redact(provenance.features, f"{root}.features", events)
    signals = redact(provenance.signals, f"{root}.signals", events)
    quality_states = redact(
        provenance.quality_states, f"{root}.quality_states", events
    )
    candidate_hash = str(
        canonical_hash(
            {"candidate_universe": candidate_universe, "rejections": rejections}
        )
    )
    prompt_hash = str(
        canonical_hash(
            {
                "prompt_bundle_version": provenance.llm.prompt_bundle_version,
                "messages": prompt_messages,
            }
        )
    )
    config_hash = str(
        canonical_hash(
            {"config_version": provenance.llm.config_version, "config": config}
        )
    )
    parsed_hash = str(canonical_hash(parsed_results))
    raw_hash = str(canonical_hash(raw_results))
    content_hashes: dict[str, JsonValue] = {
        "candidate_universe_hash": candidate_hash,
        "source_hash": str(canonical_hash(sources)),
        "feature_hash": str(canonical_hash(features)),
        "prompt_hash": prompt_hash,
        "raw_result_hash": raw_hash,
        "parsed_result_hash": parsed_hash,
        "consensus_hash": str(
            canonical_hash({"consensus": consensus, "deliberation": deliberation})
        ),
        "portfolio_state_hash": str(
            canonical_hash({"portfolio_state": portfolio, "risk_state": risk})
        ),
    }
    llm: dict[str, JsonValue] = {
        "provider_adapter_version": provenance.llm.provider_adapter_version,
        "provider": provenance.llm.provider,
        "model": provenance.llm.model,
        "provider_request_id": redact(
            provenance.llm.provider_request_id,
            f"{root}.llm.provider_request_id",
            events,
            "provider_request_id",
        ),
        "prompt_bundle_version": provenance.llm.prompt_bundle_version,
        "prompt_hash": prompt_hash,
        "prompt_messages_redacted": prompt_messages,
        "config_version": provenance.llm.config_version,
        "config_hash": config_hash,
        "parser_version": provenance.llm.parser_version,
        "parser_input_hash": raw_hash,
        "raw_results": raw_results,
        "parsed_results": parsed_results,
    }
    body: dict[str, JsonValue] = {
        "ticker": identity.ticker,
        "name": redact(identity.name, f"{root}.name", events, "name"),
        "market": identity.market,
        "exchange": identity.exchange,
        "action": identity.action,
        "decision_at": identity.decision_at,
        "emitted_at": identity.emitted_at,
        "data_cutoff_at": identity.data_cutoff_at,
        "market_context": redact(
            provenance.market_context, f"{root}.market_context", events
        ),
        "sources": sources,
        "candidate_universe": candidate_universe,
        "selection": selection,
        "rejections": rejections,
        "features": features,
        "signals": signals,
        "llm": llm,
        "consensus": consensus,
        "deliberation": deliberation,
        "portfolio_state": portfolio,
        "risk_state": risk,
        "quality_states": quality_states,
        "operator_decision": None,
        "content_hashes": content_hashes,
    }
    return PreparedRecommendation(
        recommendation,
        evidence,
        body,
        candidate_hash,
        prompt_hash,
        config_hash,
        parsed_hash,
    )
