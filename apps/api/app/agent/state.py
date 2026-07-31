from enum import StrEnum


class AgentState(StrEnum):
    OBSERVE = "observe"
    DISCOVER = "discover"
    DECIDE = "decide"
    ACT = "act"
    VERIFY = "verify"
    COMPLETE = "complete"
    BLOCKED = "blocked"


TERMINAL_STATES = frozenset({AgentState.COMPLETE, AgentState.BLOCKED})
ALLOWED_TRANSITIONS: dict[AgentState, frozenset[AgentState]] = {
    AgentState.OBSERVE: frozenset({AgentState.DISCOVER, AgentState.COMPLETE, AgentState.BLOCKED}),
    AgentState.DISCOVER: frozenset({AgentState.DECIDE, AgentState.BLOCKED}),
    AgentState.DECIDE: frozenset({AgentState.ACT, AgentState.COMPLETE, AgentState.BLOCKED}),
    AgentState.ACT: frozenset({AgentState.VERIFY, AgentState.BLOCKED}),
    AgentState.VERIFY: frozenset({AgentState.COMPLETE, AgentState.BLOCKED}),
    AgentState.COMPLETE: frozenset(),
    AgentState.BLOCKED: frozenset(),
}


def validate_transition(current: AgentState, next_state: AgentState) -> None:
    if next_state not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"Agent state transition {current} -> {next_state} is not allowed")
