# Description: Contains the chains for the main agent system
from langchain_core.prompts import SystemMessagePromptTemplate, PromptTemplate, ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

from agent.utils.model_factory import get_model

from pydantic import BaseModel, Field
import yaml
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def _get_system_prompt_from_yaml() -> str:
    with open(Path(__file__).parent / "prompts" / "opey_system.prompt.yaml", "r") as f:
        prompt_data = yaml.safe_load(f)
        logger.info("Loaded system prompt from YAML: %s", prompt_data.get("name", "Unnamed Prompt"))
    return prompt_data["prompt"]

### Main Opey agent
# Prompt
<<<<<<< HEAD
OPEY_DEFAULT_SYSTEM_PROMPT = """You are a friendly, helpful assistant for the Open Bank Project API called Opey. You are rebellious against old banking paradigms and have a sense of humor. Always give the user accurate and helpful information.

CRITICAL - No Hallucination Policy: NEVER fabricate tool calls, API responses, or data. Do not pretend to call tools or generate fake results. If you don't have the information or tools to answer a question, be honest about your limitations.

When tools are available:
- Efficiency priority: If there is a tool that can help answer the user's question, use it immediately without needing to be prompted.
- Endpoint Awareness: Use the endpoint retrieval tool to stay aware of and provide details on available API capabilities before attempting to answer questions. Assume that the endpoint retrieval tool has access to all the latest API endpoint information.
- Tool Utilization Priority: Prioritize using available tools to verify the API's capabilities before providing information.
- Task Follow Through: If you reach a snag with a tool (missing roles, permissions, or invalid input), reuse the tools to try to complete the task fully. For example, if an entitlement is missing, try to assign it using OBP API endpoints. Follow through on tasks until fully completed or you are unable to proceed.
- Transparent Error Handling: If an error occurs, promptly acknowledge and correct the mistake by using the appropriate tools to provide the correct information.

When tools are NOT available:
- Inform the user that your API tools are currently unavailable
- Suggest they try again later or contact support if the issue persists
- You can still provide general information about the Open Bank Project API based on your training, but make it clear you cannot access live data or perform actions

Adaptability and Continuous Learning: Learn from each interaction to enhance future responses, ensuring a high standard of accuracy and helpfulness.
"""
=======
opey_system_prompt_template = _get_system_prompt_from_yaml()
if not opey_system_prompt_template:
    logger.warning("Failed to load system prompt from YAML, using default prompt")
    opey_system_prompt_template = OPEY_DEFAULT_SYSTEM_PROMPT
>>>>>>> main

#prompt = hub.pull("opey_main_agent")

### Retrieval Query Formulator

class QueryFormulatorOutput(BaseModel):
    query: str = Field(description="Query to be used in vector database search of either glossary items or swagger specs for endpoints.")

query_formulator_system_prompt = """You are a query formulator that takes a list of messages and a mode: {retrieval_mode}
and tries to use the messages to come up with a short search query to search a vector database of either glossary items or partial swagger specs for API endpoints.
The query needs to be in the form of a natural sounding question that conveys the semantic intent of the message, especially the latest message from the human user.

If the mode is glossary_retrieval, optimise the query to search a glossary of technical documents for the Open Bank Project (OBP)
If the mode is endpoint_retrieval, optimise the query to search through swagger schemas of different endpoints on the Open Bank Project (OBP) API

Here are a list of API endpoint tags that you can use to help you write the query. Each tag is a keyword that is associated with a group of endpoints.
Identify the most relevant tags and use them in the query to help the vector search find the most relevant endpoints.
    
    - Old-Style
    - Transaction-Request
    - API
    - Bank
    - Account
    - Account-Access
    - Direct-Debit
    - Standing-Order
    - Account-Metadata
    - Account-Application
    - Account-Public
    - Account-Firehose
    - FirehoseData
    - PublicData
    - PrivateData
    - Transaction
    - Transaction-Firehose
    - Counterparty-Metadata
    - Transaction-Metadata
    - View-Custom
    - View-System
    - Entitlement
    - Role
    - Scope
    - OwnerViewRequired
    - Counterparty
    - KYC
    - Customer
    - Onboarding
    - User
    - User-Invitation
    - Customer-Meeting
    - Experimental
    - Person
    - Card
    - Sandbox
    - Branch
    - ATM
    - Product
    - Product-Collection
    - Open-Data
    - Consumer
    - Data-Warehouse
    - FX
    - Customer-Message
    - Metric
    - Documentation
    - Berlin-Group
    - Signing Baskets
    - UKOpenBanking
    - MXOpenFinance
    - Aggregate-Metrics
    - System-Integrity
    - Webhook
    - Mocked-Data
    - Consent
    - Method-Routing
    - WebUi-Props
    - Endpoint-Mapping
    - Rate-Limits
    - Counterparty-Limits
    - Api-Collection
    - Dynamic-Resource-Doc
    - Dynamic-Message-Doc
    - DAuth
    - Dynamic
    - Dynamic-Entity
    - Dynamic-Entity-Manage
    - Dynamic-Endpoint
    - Dynamic-Endpoint-Manage
    - JSON-Schema-Validation
    - Authentication-Type-Validation
    - Connector-Method
    - Berlin-Group-M
    - PSD2
    - Account Information Service (AIS)
    - Confirmation of Funds Service (PIIS)
    - Payment Initiation Service (PIS)
    - Directory
    - UK-AccountAccess
    - UK-Accounts
    - UK-Balances
    - UK-Beneficiaries
    - UK-DirectDebits
    - UK-DomesticPayments
    - UK-DomesticScheduledPayments
    - UK-DomesticStandingOrders
    - UK-FilePayments
    - UK-FundsConfirmations
    - UK-InternationalPayments
    - UK-InternationalScheduledPayments
    - UK-InternationalStandingOrders
    - UK-Offers
    - UK-Partys
    - UK-Products
    - UK-ScheduledPayments
    - UK-StandingOrders
    - UK-Statements
    - UK-Transactions
    - AU-Banking
"""

query_formulator_prompt_template = ChatPromptTemplate.from_messages(
    [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": query_formulator_system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        },
        MessagesPlaceholder("messages"),
    ]
)

query_formulator_llm = get_model(model_name='medium', temperature=0).with_structured_output(QueryFormulatorOutput)
query_formulator_chain = query_formulator_prompt_template | query_formulator_llm


### Conversation Summarizer



conversation_summarizer_system_prompt_template = ChatPromptTemplate.from_messages(
    [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": """You are a conversation summarizer that takes a list of messages and tries to summarize the conversation so far.\n
The messages will consist of messages from the user, responses from the chatbot, and tool calls with responses.\n
Try to summarize the conversation so far in a way that is concise and informative.\n
If there is important information in the tools or the messages,\n
such as a relevant bank ID user ID, or some other peice of data that is important to the users last message, include it in the summary message.""",
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "{existing_summary_message}\n\nList of messages: {messages}",
                }
            ]
        }
    ]
)

conversation_summarizer_llm = get_model(model_name='medium', temperature=0)
conversation_summarizer_chain = conversation_summarizer_system_prompt_template | conversation_summarizer_llm | StrOutputParser()