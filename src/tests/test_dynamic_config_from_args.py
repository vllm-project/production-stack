import dataclasses
import sys

import pytest

from vllm_router.dynamic_config import DynamicRouterConfig
from vllm_router.parsers import parser


@pytest.fixture
def parse(monkeypatch):
    def _parse(argv):
        monkeypatch.setattr(sys, "argv", ["vllm-router"] + argv)
        return parser.parse_args()

    return _parse


# Every argparse destination that is also a dataclass field is given a
# non-default value here. A field left at its default is invisible to the
# parity test below, because argparse and the dataclass are written to share
# their defaults, so both sides read the same even when from_args drops the
# assignment.
ARGV = [
    "--port",
    "8000",
    "--service-discovery",
    "static",
    "--routing-logic",
    "roundrobin",
    "--static-backends",
    "http://a:8000,http://b:8000",
    "--static-models",
    "m1,m2",
    "--static-model-types",
    "chat,chat",
    "--static-model-labels",
    "prefill,decode",
    "--static-aliases",
    "alias1:m1",
    "--prefill-model-labels",
    "prefill",
    "--decode-model-labels",
    "decode",
    "--static-backend-health-checks",
    "--static-backend-health-check-interval",
    "30",
    "--static-backend-health-check-timeout-seconds",
    "5",
    "--session-key",
    "x-session",
    "--priority-header",
    "x-priority",
    "--priority-field",
    "request_priority",
    "--priority-default",
    "7",
    "--priority-threshold",
    "3",
    "--callbacks",
    "mod.fn",
]


def test_from_args_carries_the_three_label_fields(parse):
    """DynamicConfigWatcher holds this object as current_config and /health
    serialises it, so a field the operator set and from_args dropped is
    reported as null while the router runs with it."""
    config = DynamicRouterConfig.from_args(parse(ARGV))

    assert config.static_model_labels == "prefill,decode"
    assert config.prefill_model_labels == "prefill"
    assert config.decode_model_labels == "decode"


def test_from_args_drops_no_field_the_parser_also_defines(parse):
    """Fails when a field is added to the dataclass and the parser but not to
    from_args.

    A dropped assignment leaves the field at its dataclass default, so the test
    asks whether each field moved off that default, rather than whether it
    equals the parsed argument. That catches a field whose default is truthy,
    such as static_backend_health_check_interval at 60, and it tolerates a
    transformation being moved into from_args later.
    """
    args = parse(ARGV)
    config = DynamicRouterConfig.from_args(args)

    defaults = {
        f.name: f.default
        for f in dataclasses.fields(config)
        if f.default is not dataclasses.MISSING
    }
    shared = sorted(set(defaults) & set(vars(args)))
    assert shared, "no field name is shared, so this test would pass vacuously"

    # A field the command line leaves at its dataclass default is invisible
    # here, because a dropped assignment leaves it at that same value. Fail on
    # that rather than pass quietly, so ARGV has to keep up with the dataclass.
    at_default = [name for name in shared if getattr(args, name) == defaults[name]]
    assert at_default == [], (
        "ARGV leaves these fields at their dataclass default, so the check "
        f"below cannot see them: {at_default}"
    )

    dropped = [
        name
        for name in shared
        if getattr(args, name) != defaults[name]
        and getattr(config, name) == defaults[name]
    ]
    assert dropped == []
