"""Topic layout of the demo (prefix bsg/) and Solace-style matching.

Watches carry Solace SMF wildcard syntax (``*`` = one level or a
level prefix, ``>`` = one or more trailing levels) because that is
what the market data people know from their appliances. MQTT clients
subscribe with ``+`` / ``#``; :func:`to_mqtt` converts.
"""

from __future__ import annotations

PREFIX = "bsg"

QUOTES = PREFIX + "/quotes/{issuer}/{product_class}/{isin}"
REFERENCE = PREFIX + "/reference/{underlying}"
NEWS = PREFIX + "/news"
CONTROL_SCENARIO = PREFIX + "/control/scenario"
CONTROL_SCENARIO_STATE = PREFIX + "/control/scenario/state"
CONTROL_WATCH = PREFIX + "/control/watch"
WATCH_EVENT = PREFIX + "/watches/{watch_id}/{event}"
ALERT = PREFIX + "/alerts/{watch_id}"
DESK_ACTIONS = PREFIX + "/desk/actions"
DESK_ISSUER_STATUS = PREFIX + "/desk/issuer-status/{issuer}"
DESK_NOTE = PREFIX + "/desk/notes/{watch_id}"
DESK_ERRORS = PREFIX + "/desk/errors"
DESK_PROGRESS = PREFIX + "/desk/progress/{watch_id}"
DESK_REQUEST = PREFIX + "/desk/requests/{request_id}"
DESK_REPLIES = PREFIX + "/desk/replies"
DESK_RESULTS = PREFIX + "/desk/results"


def to_mqtt(solace_filter: str) -> str:
    """Convert a Solace subscription to an MQTT filter.

    Level-prefix wildcards (``ab*``) have no MQTT equivalent and are
    widened to ``+``; :func:`matches` still applies the exact rule.
    """
    levels = solace_filter.split("/")
    out = []
    for i, lvl in enumerate(levels):
        if lvl == ">" and i == len(levels) - 1:
            out.append("#")
        elif "*" in lvl:
            out.append("+")
        else:
            out.append(lvl)
    return "/".join(out)


def matches(solace_filter: str, topic: str) -> bool:
    """Solace SMF subscription match (``*`` and trailing ``>``)."""
    f = solace_filter.split("/")
    t = topic.split("/")
    for i, lvl in enumerate(f):
        if lvl == ">" and i == len(f) - 1:
            return len(t) > i
        if i >= len(t):
            return False
        if lvl == "*":
            continue
        if lvl.endswith("*") and "*" not in lvl[:-1]:
            if not t[i].startswith(lvl[:-1]):
                return False
            continue
        if lvl != t[i]:
            return False
    return len(f) == len(t)
