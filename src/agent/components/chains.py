# Description: Contains the chains for the main agent system
from langchain_core.prompts import SystemMessagePromptTemplate, PromptTemplate, ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

from agent.utils.model_factory import get_model
from agent.components.tools import glossary_retrieval_tool, endpoint_retrieval_tool

from pydantic import BaseModel, Field
import yaml
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def _get_system_prompt_from_yaml():
    with open(Path(__file__).parent / "prompts" / "opey_system.prompt.yaml", "r") as f:
        prompt_data = yaml.safe_load(f)
        logger.info("Loaded system prompt from YAML: %s", prompt_data.get("name", "Unnamed Prompt"))
    return prompt_data["prompt"]

### Main Opey agent
# Prompt
opey_system_prompt_template = _get_system_prompt_from_yaml()

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