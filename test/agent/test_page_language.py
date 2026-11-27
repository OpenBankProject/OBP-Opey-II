"""The language of the user's page (page_language) reaches the agent as this turn's system context."""
from langchain_core.messages import SystemMessage

from agent.graph_builder import page_language_message
from schema import RegenerateInput, StreamInput
from service.streaming_legacy import _parse_input


def test_arabic_page_asks_for_arabic_answers():
    message = page_language_message({"page_language": "ar"})
    assert isinstance(message, SystemMessage)
    assert "Answer in Arabic" in message.content
    assert "Role names" in message.content


def test_an_unknown_code_is_named_as_it_is():
    assert "Answer in fr-CA" in page_language_message({"page_language": "fr-CA"}).content
    assert "Answer in English" in page_language_message({"page_language": "en-GB"}).content


def test_no_language_adds_nothing():
    assert page_language_message({}) is None
    assert page_language_message({"page_language": "  "}) is None


def test_inputs_accept_it_and_invoke_carries_it():
    kwargs, _ = _parse_input(StreamInput(message="hi", page_language="ar"), "session-1")
    assert kwargs["config"]["configurable"]["page_language"] == "ar"
    assert RegenerateInput(page_language="ar").page_language == "ar"
    kwargs, _ = _parse_input(StreamInput(message="hi"), "session-1")
    assert "page_language" not in kwargs["config"]["configurable"]
