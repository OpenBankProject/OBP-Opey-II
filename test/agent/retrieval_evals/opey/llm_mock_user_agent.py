# This llm is a langgraph agent that will attempt to use opey to carry out a desired task. 
# this will be used to test the opey agent by counting the number of user prompts it takes to complete the task

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import MemorySaver
import langgraph
from langgraph.graph.state import CompiledStateGraph

from pydantic import BaseModel, Field

from src.service.service import _parse_input
from src.schema import UserInput


model = ChatOpenAI(temperature=0, model="gpt-4o")

def create_mock_opey_user(opey_graph: CompiledStateGraph) -> CompiledStateGraph:
    """
    Create a mock Opey user agent that uses the Opey graph to carry out tasks.
    
    Args:
        opey_graph (CompiledStateGraph): The Opey graph to be used by the agent.
        
    Returns:
        CompiledStateGraph: The mock Opey user agent.
    """
    
    @tool
    async def send_opey_message(message: str) -> str | None:
        """
        Send a message to the Opey agent and receive a response. Opey is an agent that can carry out tasks on the Open Bank Project API.
        
        Args:
            message (str): The message to be sent to the Opey agent.
            
        Returns:
            str: The response from the Opey agent.
        """

        # Creates a thread ID
        _input = UserInput(
            message=message,
            is_tool_call_approval=False,
        )
        # Parse the input message
        kwargs, _ = _parse_input(_input)
        
        # Call Opey graph
        try:
            response = await opey_graph.ainvoke(**kwargs)
        except Exception as e:
            print(f"Error: {e}")
            return None

        print(f"Response: {response}")
        # Return the response
        return response

    
    mock_user_prompt = """
    You are a mock Opey user agent that uses the Opey graph to carry out tasks.

    Opey is an LLM agent that can call APIs on the Open Bank Project API.
    You are a mock user agent that will interact with Opey to carry out tasks.

    You will be given a task to carry out and you will use the Opey LLM agent to carry out that task.
    Send messages to Opey and receive responses. When you deem that the task is complete and your goal is achieved,
    return the final result with written feedback on how easy/hard it was to complete the task using Opey.

    Also give a grade from 0 to 10 on how well Opey completed the task. With 0 being completely unhelpful and 10 being completely helpful.
    """

    system_message = SystemMessage(content=mock_user_prompt)
    
    class MockOpeyUserOutput(BaseModel):
        result: str = Field(description="The final result of the task")
        feedback: str = Field(description="Feedback on how easy/hard it was to complete the task using Opey")
        grade: str = Field(description="Grade from 0 to 10 on how well Opey completed the task")

    # Create a mock Opey user agent using the Opey graph
    mock_opey_user = create_react_agent(
        model=model,
        prompt=system_message,
        response_format=MockOpeyUserOutput,
        tools=[send_opey_message],
        checkpointer=MemorySaver(),
    )
    
    return mock_opey_user