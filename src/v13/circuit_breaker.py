from __future__ import annotations

from src.v13.prd03_models import (
    CircuitKey,
    CircuitObservation,
    CircuitState,
)


def initial_state(key: CircuitKey) -> CircuitState:
    return CircuitState(key=key)


def prepare_session(state: CircuitState, key: CircuitKey) -> CircuitState:
    if state.key == key:
        return state
    return initial_state(key)


def observe_attempt(
    state: CircuitState, observation: CircuitObservation
) -> CircuitState:
    recent = (*state.recent, observation)[-20:]
    consecutive = 0 if observation.succeeded else state.consecutive_failures + 1
    recent_rule = len(recent) == 20 and sum(not item.succeeded for item in recent) >= 4
    return state.model_copy(
        update={
            "recent": recent,
            "consecutive_failures": consecutive,
            "is_open": state.is_open or consecutive >= 3 or recent_rule,
        }
    )
