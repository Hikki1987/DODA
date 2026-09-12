"""doda.ai.port scaffolding — proves NullAIPort never reads the history it
is given (so it structurally cannot leak conversation content anywhere,
independent of whatever a future real provider implementation does) and
satisfies the AIPort protocol it's meant to stand in for."""

from doda.ai.port import AIPort, NullAIPort


async def test_null_ai_port_satisfies_the_protocol() -> None:
    port: AIPort = NullAIPort()
    assert isinstance(port, AIPort)


async def test_null_ai_port_never_echoes_the_history_it_was_given() -> None:
    port = NullAIPort()
    secret = "this-must-never-appear-in-the-reply"
    reply = await port.generate_reply(conversation_history=[secret])
    assert secret not in reply


async def test_null_ai_port_reply_is_deterministic() -> None:
    port = NullAIPort()
    first = await port.generate_reply(conversation_history=[])
    second = await port.generate_reply(conversation_history=["anything"])
    assert first == second
