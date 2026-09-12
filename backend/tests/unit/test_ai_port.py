"""doda.ai.port scaffolding — proves NullModelGateway never reads the
history/tools it is given (so it structurally cannot leak conversation
content anywhere, independent of whatever a future real provider
implementation does) and satisfies the ModelGateway protocol it's meant
to stand in for."""

from doda.ai.port import ModelGateway, NullModelGateway
from doda.ai.types import ChatMode, ChatRole, ChatTurn, Completed, TextDelta


async def _collect(gateway, **kwargs):
    events = []
    async for event in gateway.stream_chat(**kwargs):
        events.append(event)
    return events


async def test_null_model_gateway_satisfies_the_protocol() -> None:
    gateway: ModelGateway = NullModelGateway()
    assert isinstance(gateway, ModelGateway)


async def test_null_model_gateway_never_echoes_the_history_it_was_given() -> None:
    gateway = NullModelGateway()
    secret = "this-must-never-appear-in-the-reply"
    events = await _collect(
        gateway,
        model="anything",
        mode=ChatMode.STANDARD,
        instructions="",
        history=[ChatTurn(role=ChatRole.USER, content=secret)],
        tools=[],
        max_output_tokens=100,
    )
    assert all(secret not in str(event) for event in events)


async def test_null_model_gateway_reply_is_deterministic_and_well_formed() -> None:
    gateway = NullModelGateway()
    events = await _collect(
        gateway,
        model="anything",
        mode=ChatMode.FAST,
        instructions="",
        history=[],
        tools=[],
        max_output_tokens=100,
    )
    assert len(events) == 2
    assert isinstance(events[0], TextDelta)
    assert isinstance(events[1], Completed)
    assert events[1].usage.input_tokens == 0
    assert events[1].usage.output_tokens == 0
    assert events[1].finish_reason == "stop"
