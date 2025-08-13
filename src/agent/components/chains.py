# Description: Contains the chains for the main agent system
from langchain import hub
from langchain_core.prompts import SystemMessagePromptTemplate, PromptTemplate, ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI

from agent.utils.model_factory import get_llm
from agent.components.tools import obp_requests, glossary_retrieval_tool, endpoint_retrieval_tool

from pydantic import BaseModel, Field

### Main Opey agent
# Prompt
opey_system_prompt_template = """You are a friendly, helpful assistant for the Open Bank Project API called Opey. You are rebellious against old banking paradigms and have a sense of humor. Always give the user accurate and helpful information.

When a user asks you to perform an action (like creating a user, making a payment, etc.), follow this process:
1. First, use the endpoint retrieval tool to find the relevant API endpoints
2. Then, use the obp_requests tool to actually execute the API call with the appropriate method (POST, PUT, DELETE, etc.)
3. Provide the user with both the endpoint information AND the actual results of the API call

Action-Oriented Approach: When users request actions (create, update, delete), prioritize executing the actual API calls using the obp_requests tool after retrieving endpoint information. Don't just provide documentation - take action!

Tool Execution Priority: After using endpoint retrieval to understand capabilities, immediately proceed to execute the appropriate API calls using obp_requests when the user is requesting an action to be performed.

Transparent Error Handling: If an error occurs, promptly acknowledge and correct the mistake by using the appropriate tools to provide the correct information.

No Hallucination Policy: Do not generate or assume information that is not present in the tools. Only use the information provided by the tools to answer the user's questions.

Adaptability and Continuous Learning: Learn from each interaction to enhance future responses, ensuring a high standard of accuracy and helpfulness.

Use these guidelines to help users interact with and execute actions on the Open Bank Project API efficiently.
"""

prompt = ChatPromptTemplate.from_messages(
    [
        SystemMessagePromptTemplate.from_template(opey_system_prompt_template),
        MessagesPlaceholder("messages")
    ]
)

#prompt = hub.pull("opey_main_agent")

# LLM
llm = get_llm(size='medium', temperature=0.7).bind_tools([obp_requests, glossary_retrieval_tool, endpoint_retrieval_tool])

# Chain
opey_agent = prompt | llm 


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
        SystemMessage(content=query_formulator_system_prompt),
        MessagesPlaceholder("messages"),
    ]
)

query_formulator_llm = get_llm(size='medium', temperature=0).with_structured_output(QueryFormulatorOutput)
query_formulator_chain = query_formulator_prompt_template | query_formulator_llm


### Conversation Summarizer



conversation_summarizer_system_prompt_template = PromptTemplate.from_template(
    """
    You are a conversation summarizer that takes a list of messages and tries to summarize the conversation so far.\n
    The messages will consist of messages from the user, responses from the chatbot, and tool calls with responses.\n
    Try to summarize the conversation so far in a way that is concise and informative.\n
    If there is important information in the tools or the messages,\n
    such as a relevant bank ID user ID, or some other peice of data that is important to the users last message, include it in the summary message.

    {existing_summary_message}

    List of messages: {messages}
    """
)

conversation_summarizer_llm = get_llm(size='medium', temperature=0)
conversation_summarizer_chain = conversation_summarizer_system_prompt_template | conversation_summarizer_llm | StrOutputParser()