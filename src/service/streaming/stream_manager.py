from typing import AsyncGenerator, Optional
from langchain_core.runnables.schema import StreamEvent as LangGraphStreamEvent
from langgraph.graph.state import CompiledStateGraph

from .events import StreamEvent, StreamEventFactory
from .processors import StreamEventOrchestrator
from schema import StreamInput, ChatMessage
from service.opey_session import OpeySession


class StreamManager:
    """Main interface for managing streaming responses"""

    def __init__(self, opey_session: OpeySession):
        self.opey_session = opey_session
        self.graph: CompiledStateGraph = opey_session.graph

    async def stream_response(
        self,
        stream_input: StreamInput,
        config: dict
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        Main method to stream a response from the agent

        Args:
            stream_input: The input configuration for streaming
            config: LangGraph configuration including thread_id

        Yields:
            StreamEvent: Clean, typed events for the frontend
        """

        orchestrator = StreamEventOrchestrator(stream_input)

        try:
            # Parse input for the graph
            if stream_input.is_tool_call_approval:
                graph_input = None
            else:
                input_message = ChatMessage(type="human", content=stream_input.message)
                graph_input = {"messages": [input_message.to_langchain()]}

            # Stream events from the graph
            kwargs = {
                "input": graph_input,
                "config": config
            }

            async for langgraph_event in self.graph.astream_events(**kwargs, version="v2"):
                # Process each LangGraph event through our orchestrator
                async for stream_event in orchestrator.process_event(langgraph_event):
                    yield stream_event

            # Check for human approval requirement
            await self._handle_approval_if_needed(orchestrator, config)

        except Exception as e:
            yield StreamEventFactory.error(
                error_message=f"Streaming error: {str(e)}",
                error_code="stream_error"
            )
        finally:
            # Always send stream end event
            yield StreamEventFactory.stream_end()

    async def _handle_approval_if_needed(
        self,
        orchestrator: StreamEventOrchestrator,
        config: dict
    ) -> AsyncGenerator[StreamEvent, None]:
        """Handle human approval requirements"""

        # Get current state to check for interruptions
        agent_state = await self.graph.aget_state(config)

        if agent_state.next and "human_review" in agent_state.next:
            messages = agent_state.values.get("messages", [])

            if messages:
                tool_call_message = messages[-1]

                if hasattr(tool_call_message, 'tool_calls') and tool_call_message.tool_calls:
                    for tool_call in tool_call_message.tool_calls:
                        # Check if this is a tool that requires approval
                        if self._requires_approval(tool_call):
                            yield StreamEventFactory.approval_request(
                                tool_name=tool_call["name"],
                                tool_call_id=tool_call["id"],
                                tool_input=tool_call["args"],
                                message=f"Approval required for {tool_call['name']} with {tool_call['args'].get('method', 'unknown')} request"
                            )

    def _requires_approval(self, tool_call: dict) -> bool:
        """Determine if a tool call requires human approval"""

        # Tools that require approval (non-GET OBP requests)
        if tool_call["name"] == "obp_requests":
            method = tool_call["args"].get("method", "").upper()
            return method != "GET"

        return False

    async def continue_after_approval(
        self,
        thread_id: str,
        tool_call_id: str,
        approved: bool,
        stream_input: StreamInput
    ) -> AsyncGenerator[StreamEvent, None]:
        """Continue streaming after human approval/denial"""

        config = {"configurable": {"thread_id": thread_id}}

        try:
            if approved:
                # Continue to the tools node
                await self.graph.aupdate_state(
                    config,
                    values=None,
                    as_node="human_review",
                )
            else:
                # Inject a denial message
                from langchain_core.messages import ToolMessage
                await self.graph.aupdate_state(
                    config,
                    {"messages": [ToolMessage(
                        content="User denied request to OBP API",
                        tool_call_id=tool_call_id
                    )]},
                    as_node="tools",
                )

            # Continue streaming the response
            orchestrator = StreamEventOrchestrator(stream_input)

            async for langgraph_event in self.graph.astream_events(
                input=None,
                config=config,
                version="v2"
            ):
                async for stream_event in orchestrator.process_event(langgraph_event):
                    yield stream_event

        except Exception as e:
            yield StreamEventFactory.error(
                error_message=f"Error continuing after approval: {str(e)}",
                error_code="approval_continuation_error"
            )
        finally:
            yield StreamEventFactory.stream_end()

    def to_sse_format(self, event: StreamEvent) -> str:
        """Convert a stream event to SSE format"""
        return event.to_sse_data()
