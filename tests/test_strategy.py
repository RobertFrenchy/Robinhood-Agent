from types import SimpleNamespace

from robinhood_agent.strategy import ClaudeDecider


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def client_returning(response):
    messages = FakeMessages(response)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def test_parses_structured_output():
    text = '{"market_view":"calm","decisions":[{"symbol":"SPY","action":"buy","dollars":50,"confidence":0.7,"rationale":"trend"}]}'
    resp = SimpleNamespace(
        stop_reason="end_turn", stop_details=None, content=[SimpleNamespace(type="text", text=text)]
    )
    client, messages = client_returning(resp)
    out = ClaudeDecider("claude-opus-5-5", client=client).decide({"x": 1})
    assert out.decisions[0].symbol == "SPY"
    assert messages.kwargs["output_config"]["format"]["type"] == "json_schema"
    assert messages.kwargs["fallbacks"] == "default"


def test_refusal_means_hold():
    resp = SimpleNamespace(stop_reason="refusal", stop_details={"category": None}, content=[])
    client, _ = client_returning(resp)
    out = ClaudeDecider("claude-opus-5-5", client=client).decide({})
    assert out.decisions == []
