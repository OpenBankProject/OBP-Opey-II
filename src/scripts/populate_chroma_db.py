#!/usr/bin/env python3
"""
Script to populate ChromaDB with OBP glossary and endpoint documentation.
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
from langchain.text_splitter import RecursiveCharacterTextSplitter

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

    for item in glossary_items:
        if not isinstance(item, dict):
            continue

        # Try different field name variations
        title = item.get("title") or item.get("name") or item.get("term") or ""

        # Handle description which might be a string or an object with markdown
        description_raw = item.get("description") or item.get("definition") or item.get("desc") or ""
        description = ""

        if isinstance(description_raw, dict):
            # If description is an object, try to get markdown or text content
            description = description_raw.get("markdown") or description_raw.get("text") or description_raw.get("content") or str(description_raw)
        elif isinstance(description_raw, str):
            description = description_raw
        else:
            description = str(description_raw) if description_raw else ""

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

def process_swagger_data(swagger_data: Dict[str, Any]) -> List[Document]:
    """Process OBP swagger documentation into documents for vector storage."""
    documents = []

    # Process paths (endpoints)
    paths = swagger_data.get("paths", {})
    print(f"Processing {len(paths)} API endpoints...")

    for path, methods in paths.items():
        for method, details in methods.items():
            if isinstance(details, dict):
                # Extract key information
                summary = details.get("summary", "")
                description = details.get("description", "")
                tags = details.get("tags", [])
                operation_id = details.get("operationId", "")

                # Process parameters
                parameters = details.get("parameters", [])
                processed_params = []
                for param in parameters:
                    param_data = {
                        "name": param.get("name", ""),
                        "type": param.get("type", param.get("schema", {}).get("type", "")),
                        "description": param.get("description", ""),
                        "required": param.get("required", False)
                    }
                    processed_params.append(param_data)

                # Process responses
                responses = details.get("responses", {})
                processed_responses = {}
                for status_code, response_detail in responses.items():
                    processed_responses[status_code] = {
                        "description": response_detail.get("description", "")
                    }

                # Create structured JSON data
                endpoint_data = {
                    "endpoint": f"{method.upper()} {path}",
                    "summary": summary,
                    "description": description,
                    "operation_id": operation_id,
                    "tags": tags,
                    "parameters": processed_params,
                    "responses": processed_responses
                }

                # Create search-friendly content for embedding
                search_content_parts = [
                    f"Endpoint: {method.upper()} {path}",
                    f"Summary: {summary}" if summary else "",
                    f"Description: {description}" if description else "",
                    f"Operation ID: {operation_id}" if operation_id else "",
                    f"Tags: {', '.join(tags)}" if tags else "",
                ]

                # Add parameter info for search
                if processed_params:
                    search_content_parts.append("Parameters:")
                    for param in processed_params:
                        search_content_parts.append(f"- {param['name']} ({param['type']}): {param['description']} {'[Required]' if param['required'] else '[Optional]'}")

                # Add response info for search
                if processed_responses:
                    search_content_parts.append("Responses:")
                    for status_code, response_data in processed_responses.items():
                        search_content_parts.append(f"- {status_code}: {response_data['description']}")

                search_content = "\n".join([part for part in search_content_parts if part])

                # Create metadata
                metadata = {
                    "source": "obp_endpoints",
                    "path": path,
                    "method": method.upper(),
                    "operation_id": operation_id,
                    "tags": ", ".join(tags) if tags else "",
                    "type": "api_endpoint"
                }

                # Store JSON string as page_content for compatibility with existing code
                documents.append(Document(
                    page_content=json.dumps(endpoint_data),
                    metadata=metadata
                ))

                # Also store search-friendly version for better retrieval
                search_metadata = metadata.copy()
                search_metadata["type"] = "api_endpoint_search"
                documents.append(Document(
                    page_content=search_content,
                    metadata=search_metadata
                ))

    # Process components/schemas if they exist
    components = swagger_data.get("components", {})
    schemas = components.get("schemas", {})

    if schemas:
        print(f"Processing {len(schemas)} schema definitions...")

        for schema_name, schema_details in schemas.items():
            # Create structured schema data
            schema_data = {
                "schema_name": schema_name,
                "description": schema_details.get("description", ""),
                "properties": {}
            }

            if "properties" in schema_details:
                for prop_name, prop_details in schema_details["properties"].items():
                    schema_data["properties"][prop_name] = {
                        "type": prop_details.get("type", ""),
                        "description": prop_details.get("description", "")
                    }

            # Create search-friendly content
            search_content = f"Schema: {schema_name}\n"
            if schema_data["description"]:
                search_content += f"Description: {schema_data['description']}\n"

            if schema_data["properties"]:
                search_content += "Properties:\n"
                for prop_name, prop_data in schema_data["properties"].items():
                    search_content += f"- {prop_name} ({prop_data['type']}): {prop_data['description']}\n"

            metadata = {
                "source": "obp_endpoints",
                "schema_name": schema_name,
                "type": "schema_definition"
            }

            # Store JSON string as page_content
            documents.append(Document(
                page_content=json.dumps(schema_data),
                metadata=metadata
            ))

            # Also store search-friendly version
            search_metadata = metadata.copy()
            search_metadata["type"] = "schema_definition_search"
            documents.append(Document(
                page_content=search_content,
                metadata=search_metadata
            ))

    print(f"Created {len(documents)} endpoint/schema documents")
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
