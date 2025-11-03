#!/usr/bin/env python3
"""
Script to fix ChromaDB collection metadata by adding missing _type field.
This resolves the KeyError: '_type' issue when using langchain-chroma with ChromaDB 0.5.x
"""

import sqlite3
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Get ChromaDB directory from environment
chroma_dir = os.getenv("CHROMADB_DIRECTORY", "/src/data/test_chroma_langchain_db")
db_path = Path(chroma_dir) / "chroma.sqlite3"

print(f"Fixing ChromaDB metadata at: {db_path}")
print(f"Database exists: {db_path.exists()}")

if not db_path.exists():
    print(f"ERROR: Database not found at {db_path}")
    exit(1)

try:
    # Connect to the database
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Get all collections and their configurations
    cursor.execute("SELECT id, name, config_json_str FROM collections")
    collections = cursor.fetchall()

    print(f"\nFound {len(collections)} collections:")

    for coll_id, coll_name, config_str in collections:
        print(f"\n  Processing collection: {coll_name} (ID: {coll_id})")

        if not config_str:
            print(f"    WARNING: No configuration found, skipping")
            continue

        # Parse the existing configuration
        try:
            config = json.loads(config_str)
        except json.JSONDecodeError as e:
            print(f"    ERROR: Failed to parse config JSON: {e}")
            continue

        # Check if configuration has correct structure and no invalid fields
        has_correct_structure = (
            "_type" in config
            and "hnsw_configuration" in config
            and "embedding_function" not in config
            and "vector_index" not in config
        )

        if has_correct_structure:
            print(f"    ✓ Configuration already has correct structure")
            continue

        # Create the correct configuration structure for ChromaDB 0.5.x
        # Move vector_index.hnsw to the root level as hnsw_configuration
        new_config = {"_type": "CollectionConfigurationInternal"}

        # Extract HNSW parameters if they exist
        if "vector_index" in config and "hnsw" in config["vector_index"]:
            hnsw_params = config["vector_index"]["hnsw"]
            new_config["hnsw_configuration"] = {
                "_type": "HNSWConfigurationInternal",
                "space": hnsw_params.get("space", "l2"),
                "ef_construction": hnsw_params.get("ef_construction", 100),
                "ef_search": hnsw_params.get("ef_search", 100),
                "num_threads": hnsw_params.get("num_threads", 4),
                "M": hnsw_params.get("max_neighbors", 16),
                "resize_factor": hnsw_params.get("resize_factor", 1.2),
                "batch_size": hnsw_params.get("batch_size", 100),
                "sync_threshold": hnsw_params.get("sync_threshold", 1000),
            }
        else:
            # Use default HNSW configuration
            new_config["hnsw_configuration"] = {
                "_type": "HNSWConfigurationInternal",
                "space": "l2",
                "ef_construction": 100,
                "ef_search": 100,
                "num_threads": 4,
                "M": 16,
                "resize_factor": 1.2,
                "batch_size": 100,
                "sync_threshold": 1000,
            }

        # DO NOT preserve embedding_function - it's not a valid ChromaDB parameter
        # embedding_function is only used by Langchain, not stored in ChromaDB config

        # Convert to JSON string
        new_config_str = json.dumps(new_config)

        # Update the database
        cursor.execute(
            "UPDATE collections SET config_json_str = ? WHERE id = ?",
            (new_config_str, coll_id),
        )

        print(f"    ✓ Updated configuration structure")
        print(f"    Old config: {config_str[:150]}...")
        print(f"    New config: {new_config_str[:150]}...")

    # Commit the changes
    conn.commit()
    print(f"\n✓ Successfully updated {len(collections)} collections")
    print(f"✓ Changes committed to database")

    # Verify the changes
    print(f"\nVerifying changes...")
    cursor.execute("SELECT name, config_json_str FROM collections")
    for name, config_str in cursor.fetchall():
        config = json.loads(config_str)
        has_type = "_type" in config
        has_hnsw = "hnsw_configuration" in config
        status = "✓" if (has_type and has_hnsw) else "✗"
        print(
            f"  {status} {name}: _type={'present' if has_type else 'MISSING'}, hnsw_configuration={'present' if has_hnsw else 'MISSING'}"
        )

    conn.close()
    print(f"\n✓ Metadata fix complete!")

except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback

    traceback.print_exc()
    exit(1)
