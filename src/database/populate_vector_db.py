#!/usr/bin/env python3
"""
Script to populate ChromaDB with OBP glossary and endpoint documentation.
This script matches the original working database format.
"""

import os
import sys
import json
import requests
from typing import List, Dict, Any
from dotenv import load_dotenv

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain.schema import Document

# Load environment variables
load_dotenv()

def get_obp_config():
    """Get OBP configuration from environment variables."""
    base_url = os.getenv("OBP_BASE_URL")
    api_version = os.getenv("OBP_API_VERSION")
    chroma_dir = os.getenv("CHROMADB_DIRECTORY")

    if not all([base_url, api_version, chroma_dir]):
        raise ValueError("Missing required environment variables: OBP_BASE_URL, OBP_API_VERSION, CHROMADB_DIRECTORY")

    return {
        "base_url": base_url,
        "api_version": api_version,
        "chroma_dir": chroma_dir,
        "glossary_url": f"{base_url}/obp/{api_version}/api/glossary",
        "swagger_url": f"{base_url}/obp/{api_version}/resource-docs/{api_version}/swagger?content=static"
    }

def fetch_obp_data(url: str) -> Dict[str, Any]:
    """Fetch data from OBP endpoint."""
    print(f"Fetching data from: {url}")

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from {url}: {e}")
        raise

def process_glossary_data(glossary_data: Dict[str, Any]) -> List[Document]:
    """Process OBP glossary data into documents for vector storage."""
    documents = []

    # Debug: Print the structure to understand the data format
    print(f"Glossary data keys: {list(glossary_data.keys()) if isinstance(glossary_data, dict) else 'Not a dict'}")

    # Try different possible structures for glossary data
    glossary_items = []
    if isinstance(glossary_data, dict):
        # Try common field names including the actual one we found
        for key in ['glossary_items', 'glossary', 'items', 'data', 'results']:
            if key in glossary_data:
                glossary_items = glossary_data[key]
                break

        # If no standard key found, check if the whole response is the glossary
        if not glossary_items and all(isinstance(v, dict) and ('title' in v or 'description' in v) for v in glossary_data.values()):
            glossary_items = list(glossary_data.values())
    elif isinstance(glossary_data, list):
        glossary_items = glossary_data

    print(f"Found {len(glossary_items)} glossary items to process")

    # Debug: Print first item structure if available
    if glossary_items and len(glossary_items) > 0:
        print(f"Sample glossary item keys: {list(glossary_items[0].keys()) if isinstance(glossary_items[0], dict) else 'Not a dict'}")
        print(f"Sample description structure: {type(glossary_items[0].get('description', ''))}")

    for item in glossary_items:
        if not isinstance(item, dict):
            continue

        # Extract title
        title = item.get("title") or item.get("name") or item.get("term") or ""

        # Handle description which might be a string or an object with markdown/html
        description_raw = item.get("description") or item.get("definition") or item.get("desc") or ""
        description = ""

        if isinstance(description_raw, dict):
            # If description is an object, prefer markdown over html, then other text fields
            description = (description_raw.get("markdown") or 
                          description_raw.get("html") or 
                          description_raw.get("text") or 
                          description_raw.get("content") or 
                          str(description_raw))
        elif isinstance(description_raw, str):
            description = description_raw
        else:
            description = str(description_raw) if description_raw else ""

        # Clean up the description - remove excessive whitespace and newlines
        if description:
            description = description.strip()
            # Skip items with empty or whitespace-only descriptions
            if not description:
                continue

        if title and description:
            # Create a comprehensive text for embedding
            content = f"Title: {title}\nDescription: {description}"

            # Add metadata for filtering and identification
            metadata = {
                "source": "obp_glossary",
                "title": title,
                "type": "glossary_item"
            }

            documents.append(Document(
                page_content=content,
                metadata=metadata
            ))

    print(f"Created {len(documents)} glossary documents")
    return documents

def get_all_obp_tags() -> List[str]:
    """Get all possible OBP tags for metadata initialization."""
    return [
        "Old-Style", "Transaction-Request", "API", "Bank", "Account", "Account-Access",
        "Direct-Debit", "Standing-Order", "Account-Metadata", "Account-Application",
        "Account-Public", "Account-Firehose", "FirehoseData", "PublicData", "PrivateData",
        "Transaction", "Transaction-Firehose", "Counterparty-Metadata", "Transaction-Metadata",
        "View-Custom", "View-System", "Entitlement", "Role", "Scope", "OwnerViewRequired",
        "Counterparty", "KYC", "Customer", "Onboarding", "User", "User-Invitation",
        "Customer-Meeting", "Experimental", "Person", "Card", "Sandbox", "Branch", "ATM",
        "Product", "Product-Collection", "Open-Data", "Consumer", "Data-Warehouse", "FX",
        "Customer-Message", "Metric", "Documentation", "Berlin-Group", "Signing Baskets",
        "UKOpenBanking", "MXOpenFinance", "Aggregate-Metrics", "System-Integrity", "Webhook",
        "Mocked-Data", "Consent", "Method-Routing", "WebUi-Props", "Endpoint-Mapping",
        "Rate-Limits", "Counterparty-Limits", "Api-Collection", "Dynamic-Resource-Doc",
        "Dynamic-Message-Doc", "DAuth", "Dynamic", "Dynamic-Entity", "Dynamic-Entity-Manage",
        "Dynamic-Endpoint", "Dynamic-Endpoint-Manage", "JSON-Schema-Validation",
        "Authentication-Type-Validation", "Connector-Method", "Berlin-Group-M", "PSD2",
        "Account Information Service (AIS)", "Confirmation of Funds Service (PIIS)",
        "Payment Initiation Service (PIS)", "Directory", "UK-AccountAccess", "UK-Accounts",
        "UK-Balances", "UK-Beneficiaries", "UK-DirectDebits", "UK-DomesticPayments",
        "UK-DomesticScheduledPayments", "UK-DomesticStandingOrders", "UK-FilePayments",
        "UK-FundsConfirmations", "UK-InternationalPayments", "UK-InternationalScheduledPayments",
        "UK-InternationalStandingOrders", "UK-Offers", "UK-Partys", "UK-Products",
        "UK-ScheduledPayments", "UK-StandingOrders", "UK-Statements", "UK-Transactions",
        "AU-Banking"
    ]

def process_swagger_data(swagger_data: Dict[str, Any]) -> List[Document]:
    """Process OBP swagger documentation into documents matching original format."""
    documents = []
    all_tags = get_all_obp_tags()

    # Process paths (endpoints)
    paths = swagger_data.get("paths", {})
    print(f"Processing {len(paths)} API endpoints...")

    for path, methods in paths.items():
        for method, details in methods.items():
            if isinstance(details, dict):
                # Extract key information
                summary = details.get("summary", "")
                operation_id = details.get("operationId", "")
                tags = details.get("tags", [])

                # Create the raw JSON content that matches original format
                # This is a single path object as it appears in swagger
                path_content = {path: {method: details}}

                # Convert to JSON string for storage
                content = json.dumps(path_content)

                # Create metadata that matches original format
                metadata = {
                    "document_id": f"{method.upper()}-{path.replace('/', '-').replace('{', '').replace('}', '')}",
                    "method": method.upper(),
                    "operation_id": operation_id,
                    "path": path,
                    "tags": ", ".join(tags) if tags else ""
                }

                # Add OBP tag metadata (all false except for matching tags)
                for tag in all_tags:
                    metadata[f"OBP_tag_{tag}"] = tag in tags

                documents.append(Document(
                    page_content=content,
                    metadata=metadata
                ))

    print(f"Created {len(documents)} endpoint documents")
    return documents

def setup_vector_store(collection_name: str, chroma_dir: str) -> Chroma:
    """Set up ChromaDB vector store."""
    embeddings = OpenAIEmbeddings(model="text-embedding-3-large")

    # Ensure directory exists
    os.makedirs(chroma_dir, exist_ok=True)

    vector_store = Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=chroma_dir
    )

    return vector_store

def populate_collection(documents: List[Document], collection_name: str, chroma_dir: str):
    """Populate a specific ChromaDB collection with documents."""
    if not documents:
        print(f"No documents to add to {collection_name}")
        return

    print(f"Setting up vector store for collection: {collection_name}")
    vector_store = setup_vector_store(collection_name, chroma_dir)

    print(f"Adding {len(documents)} documents to {collection_name}...")

    # Clear existing collection
    try:
        vector_store.delete_collection()
        print(f"Cleared existing {collection_name} collection")
    except Exception as e:
        print(f"Note: Could not clear existing collection (this is normal if collection doesn't exist): {e}")

    # Recreate vector store after clearing
    vector_store = setup_vector_store(collection_name, chroma_dir)

    # Add documents in batches to avoid memory issues
    batch_size = 100
    for i in range(0, len(documents), batch_size):
        batch = documents[i:i + batch_size]
        vector_store.add_documents(batch)
        print(f"Added batch {i//batch_size + 1}/{(len(documents) + batch_size - 1)//batch_size}")

    print(f"Successfully populated {collection_name} with {len(documents)} documents")

def main():
    """Main function to populate ChromaDB collections."""
    print("Starting ChromaDB population script...")

    try:
        # Get configuration
        config = get_obp_config()

        # Fetch data from OBP endpoints
        print("\n" + "="*50)
        print("FETCHING OBP DATA")
        print("="*50)

        glossary_data = fetch_obp_data(config["glossary_url"])
        swagger_data = fetch_obp_data(config["swagger_url"])

        # Process data into documents
        print("\n" + "="*50)
        print("PROCESSING DATA")
        print("="*50)

        glossary_documents = process_glossary_data(glossary_data)
        endpoint_documents = process_swagger_data(swagger_data)

        # Populate collections
        print("\n" + "="*50)
        print("POPULATING CHROMADB")
        print("="*50)

        populate_collection(glossary_documents, "obp_glossary", config["chroma_dir"])
        populate_collection(endpoint_documents, "obp_endpoints", config["chroma_dir"])

        print("\n" + "="*50)
        print("POPULATION COMPLETE")
        print("="*50)
        print(f"Glossary items: {len(glossary_documents)}")
        print(f"Endpoint documents: {len(endpoint_documents)}")
        print(f"Total documents: {len(glossary_documents) + len(endpoint_documents)}")

    except Exception as e:
        print(f"Error during population: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
