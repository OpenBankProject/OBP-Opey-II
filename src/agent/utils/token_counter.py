import os
from typing import Optional
from .model_factory import get_model, get_context_window, get_max_tokens
from langchain_core.messages import BaseMessage
from langchain_core.messages.utils import count_tokens_approximately

def count_tokens_from_messages(messages: list[BaseMessage], model_name: str, model_kwargs: Optional[dict] = None) -> int:
    """Count the number of tokens in a list of messages for a given model.

    Args:
        messages (list[BaseMessage]): The list of messages to count tokens for.
        model_name (str): The name of the model to use for token counting.
        model_kwargs (Optional[dict]): Additional keyword arguments for the model.

    Returns:
        int: The total number of tokens in the messages.
    """
    total_tokens = 0
    model_kwargs = model_kwargs or {}

    counting_llm = get_model(model_name, **model_kwargs)
    
    try:
        total_tokens += counting_llm.get_num_tokens_from_messages(messages)
    except NotImplementedError as e:
        print(f"Could not count tokens for model provider {os.getenv('MODEL_PROVIDER')}:\n{e}\n\nApproximating token count...")
        total_tokens += count_tokens_approximately(messages)
    
    return total_tokens
        
def count_tokens(message: BaseMessage, model_name: str, model_kwargs: Optional[dict] = None) -> int:
    """Count the number of tokens in a single message for a given model.

    Args:
        message (BaseMessage): The message to count tokens for.
        model_name (str): The name of the model to use for token counting.
        model_kwargs (Optional[dict]): Additional keyword arguments for the model.

    Returns:
        int: The number of tokens in the message.
    """
    return count_tokens_from_messages([message], model_name, model_kwargs)