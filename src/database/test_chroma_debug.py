#!/usr/bin/env python3
"""Debug script to test ChromaDB collection access"""

import chromadb
from pathlib import Path

# Path to your ChromaDB directory
# Use environment variable or default to Docker/remote server path
import os

chroma_dir_str = os.getenv("CHROMADB_DIRECTORY", "src/data/test_chroma_langchain_db")
chroma_dir = Path(chroma_dir_str)

print(f"Testing ChromaDB at: {chroma_dir}")
print(f"Directory exists: {chroma_dir.exists()}")

try:
    # Create client
    print("\n1. Creating ChromaDB client...")
    client = chromadb.PersistentClient(path=str(chroma_dir))
    print("   ✓ Client created successfully")

    # List collections
    print("\n2. Listing collections...")
    collections = client.list_collections()
    print(f"   Found {len(collections)} collections:")
    for col in collections:
        print(f"   - {col.name} (id: {col.id})")

    # Try to get each collection
    print("\n3. Attempting to get collections...")
    for col in collections:
        try:
            print(f"\n   Getting collection: {col.name}")
            collection = client.get_collection(name=col.name)
            count = collection.count()
            print(f"   ✓ Success! Collection has {count} documents")

            # Try to peek at first document
            if count > 0:
                peek = collection.peek(limit=1)
                print(
                    f"   Sample document IDs: {peek['ids'][:1] if peek['ids'] else 'None'}"
                )

        except Exception as e:
            print(f"   ✗ Error getting collection {col.name}: {e}")
            import traceback

            traceback.print_exc()

except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback

    traceback.print_exc()
