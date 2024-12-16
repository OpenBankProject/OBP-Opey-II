import asyncio
import uuid

from langsmith import aevaluate
from agent import opey_graph_eval
from langgraph.graph.state import CompiledStateGraph
from evals.end_to_end.evaluators import correct

async def run_opey(inputs: dict) -> dict:
  _input = {"messages": [{"role": "user", "content": inputs['input']}]}
  config = {"configurable": {"thread_id": str(uuid.uuid4())}}
  result = await opey_graph_eval.ainvoke(_input, config)
  return result

# We use LCEL declarative syntax here.
# Remember that langgraph graphs are also langchain runnables.
async def run_eval():


    experiment_results = await aevaluate(
        run_opey,
        data="opey-test-2",
        evaluators=[correct],
        max_concurrency=4,  # optional
        experiment_prefix="claude-3.5-baseline",  # optional
    )

    return experiment_results



if __name__ == "__main__":
   results = asyncio.run(run_eval())
   print(results)