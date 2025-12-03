import pytest
from langsmith import testing as t
import os

from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_openai.chat_models import ChatOpenAI

# Import the opey agent to test tool calling
from src.agent.components.chains import opey_agent

# Import the graph and relavant nodes from the endpoint_retrieval_graph
from src.agent.components.sub_graphs.endpoint_retrieval.endpoint_retrieval_graph import endpoint_retrieval_graph
from src.agent.components.sub_graphs.endpoint_retrieval.components.nodes import (
    retrieve_endpoints,
    grade_documents,
    return_documents,
)


os.environ["LANGSMITH_TEST_SUITE"] = "opey-endpoint-retrieval"


@pytest.mark.langsmith
@pytest.mark.parametrize(
    "user_question",
    [
        "What are the top APIs?",
        "What is the API usage information?",
        "Can you provide me with API usage information?",
        "How would I create a new Bank at OBP?",
        "Who is the current user?",
        "What are consents?",
        "How can I create a new customer?",
        "Create a new account at a bank please.",
        "is there a user with the id 1234567890?",
    ]
)
async def test_endpoint_retrieval_tool_calling(user_question):
    """
    Test the endpoint retrieval tool calling functionality of the Opey agent.
    
    Args:
        user_question (str): The input question from the user.
    """
    
    # Create a HumanMessage with the user question
    message = HumanMessage(content=user_question)
    
    # Run the Opey agent with the provided message
    result: AIMessage = await opey_agent.ainvoke({"messages": [message]})
    
    # Log the outputs and reference outputs
    t.log_outputs({"result": result})

    assert len(result.tool_calls) > 0
    assert result.tool_calls[0]["name"] == "retrieve_endpoints"

    # Call the tool for endpoint retrieval to get the output documents
    tool_call = result.tool_calls[0]
    query = tool_call["args"]["question"]
    print(f"Query: {query}")
    print(f"Tool call: {tool_call}")

    result = await endpoint_retrieval_graph.ainvoke({"question": query})

    # Use LLM as judge to evaluate if the input question to the endpoint retrieval tool is any good
    with t.trace_feedback():
        llm = ChatOpenAI(
            temperature=0,
            model="gpt-4o",
        )

        class QueryGraderOutput(BaseModel):
            score: int = Field(description="Score from 0 to 10")
            feedback: str = Field(description="Feedback on the query quality")

        messages = [
            SystemMessage(
                content="""You are a helpful assistant that evaluates the quality of the input question to the endpoint retrieval tool." \
                
                You should consider the user's original question. Then the query formulated to the RAG system.

                Give a score from 0 to 10, where 0 is a bad query and 10 is a good query. Based on how relevant the resulting documents from the retriever are to the user's original question/ message.\
                
                Also give a short written feedback (max 2 sentences) on the quality of the query.\
                """
            ),

            HumanMessage(content=f"User question: {user_question}\n\nQuery Formulated By LLM: {query}\n\nResulting documents: {result['output_documents']}\n\n"),
        ]

        score_result = llm.with_structured_output(QueryGraderOutput).invoke(messages)

        t.log_feedback(key='score', score=score_result.score)
        t.log_feedback(key='feedback', score=score_result.feedback)

