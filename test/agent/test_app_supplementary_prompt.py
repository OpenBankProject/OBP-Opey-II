"""The calling app's own focus (app_supplementary_prompt) reaches the agent as this turn's system context."""
from langchain_core.messages import SystemMessage

from agent.graph_builder import app_supplementary_message
from schema import RegenerateInput, StreamInput
from service.streaming_legacy import _parse_input


def test_the_apps_prompt_becomes_a_system_message():
    message = app_supplementary_message({"app_supplementary_prompt": "Cohort runs startup programmes."})
    assert isinstance(message, SystemMessage)
    assert message.content.endswith("Cohort runs startup programmes.")


def test_no_prompt_adds_nothing():
    assert app_supplementary_message({}) is None
    assert app_supplementary_message({"app_supplementary_prompt": "   "}) is None


def test_inputs_accept_it_and_invoke_carries_it():
    stream_input = StreamInput(message="hi", app_supplementary_prompt="Focus on Cohort.")
    kwargs, _ = _parse_input(stream_input, "session-1")
    assert kwargs["config"]["configurable"]["app_supplementary_prompt"] == "Focus on Cohort."
    assert RegenerateInput().app_supplementary_prompt is None
    kwargs, _ = _parse_input(StreamInput(message="hi"), "session-1")
    assert "app_supplementary_prompt" not in kwargs["config"]["configurable"]
