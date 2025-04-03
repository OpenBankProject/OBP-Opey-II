import pytest
from langsmith import testing as t

# Import the graph and relavant nodes from the endpoint_retrieval_graph
from src.agent.components.sub_graphs.endpoint_retrieval.endpoint_retrieval_graph import endpoint_retrieval_graph
from src.agent.components.sub_graphs.endpoint_retrieval.components.nodes import (
    retrieve_endpoints,
    grade_documents,
    return_documents,
)

@pytest.mark.langsmith
@pytest.mark.parametrize(
    "query, expected_endpoints_operationIDs",
    [
        (
            "API information",
            [
                "root",
                "getTopAPIs",
            ]
        ),
        (
            "API usage information",
            [
                "getTopAPIs",
                "getMetricsTopConsumers",
                "getAggregateMetrics",
                "getMetrics",
            ]
        ),
    ]
)
async def test_end_to_end_graph(query, expected_endpoints_operationIDs):
    """
    Test the end-to-end functionality of the endpoint retrieval graph.
    
    Args:
        query (str): The input query to test.
        expected_endpoints (list): The expected endpoints to be retrieved.
    """
    

    # Run the graph with the provided query
    result = await endpoint_retrieval_graph.ainvoke({"question": query})

    # Assert that the output matches the expected endpoints
    result_operationIDs = [
        doc["operation_id"] for doc in result["output_documents"]
    ]

    t.log_outputs({"operationIDs": result_operationIDs})

    t.log_reference_outputs(
        {"operationIDs": expected_endpoints_operationIDs}
    )

    print(f"Result operation IDs: {result_operationIDs}")

    # Calculate the accuracy as being the intersection of the expected vs resultant endpoint operation IDs
    accuracy = len(
        set(result_operationIDs).intersection(expected_endpoints_operationIDs)
    ) / len(expected_endpoints_operationIDs)
    
    t.log_feedback(key='accuracy', score=accuracy)
        
    assert accuracy >= 0.8, f"Expected 80% of {expected_endpoints_operationIDs}, but got {result_operationIDs}\n\n with accuracy: {accuracy}"



def test_basic():
    assert True