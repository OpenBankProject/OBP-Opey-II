#!/usr/bin/env python3
"""
Script to check if OBP data has changed without updating the database.

This is useful for:
- Checking if an update would be triggered before starting the service
- Monitoring OBP data changes without automatic updates
- Debugging hash comparison logic
"""

import sys
import os
from pathlib import Path

# Add src to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from database.data_hash_manager import DataHashManager
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def main():
    """Check for OBP data changes."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Check if OBP data has changed since last import"
    )
    parser.add_argument(
        "--endpoints",
        choices=["static", "dynamic", "all"],
        default="all",
        help="Type of endpoints to check (default: all)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed hash information"
    )
    args = parser.parse_args()
    
    try:
        print("🔍 Checking for OBP data changes...")
        print(f"   Endpoint type: {args.endpoints}")
        print()
        
        # Initialize hash manager
        manager = DataHashManager()
        
        # Fetch current hashes
        print("📥 Fetching current OBP data...")
        current_hashes = manager.fetch_current_data_hashes(args.endpoints)
        
        # Load stored hashes
        stored_hashes = manager.load_stored_hashes()
        
        if args.verbose:
            print("\n📊 Hash Details:")
            print(f"   Current Glossary Hash:  {current_hashes['glossary']}")
            print(f"   Current Endpoints Hash: {current_hashes['endpoints']}")
            if stored_hashes:
                print(f"   Stored Glossary Hash:   {stored_hashes.get('glossary', 'N/A')}")
                print(f"   Stored Endpoints Hash:  {stored_hashes.get('endpoints', 'N/A')}")
            else:
                print("   Stored Hashes: None (first run)")
            print()
        
        # Compare hashes
        needs_update, changes = manager.compare_hashes(current_hashes, stored_hashes)
        
        # Display results
        print("=" * 60)
        if needs_update:
            print("⚠️  DATABASE UPDATE NEEDED")
            print("=" * 60)
            if stored_hashes is None:
                print("Reason: No previous data hash found (first run)")
            else:
                changed_items = [k for k, v in changes.items() if v]
                print(f"Reason: Changes detected in: {', '.join(changed_items)}")
                print()
                for item, changed in changes.items():
                    status = "CHANGED ⚠️" if changed else "unchanged ✓"
                    print(f"  - {item.capitalize()}: {status}")
        else:
            print("✅ DATABASE IS UP TO DATE")
            print("=" * 60)
            print("No changes detected - database update not needed")
        print()
        
        # Show recommendation
        if needs_update:
            print("💡 Recommendations:")
            print("   1. Run: python src/database/populate_vector_db.py --endpoints", args.endpoints)
            print("   2. Or enable automatic updates: UPDATE_DATABASE_ON_STARTUP=true")
            print()
            return 1  # Exit code 1 indicates update needed
        else:
            print("💡 Your database has the latest OBP data")
            print()
            return 0  # Exit code 0 indicates no update needed
            
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 2  # Exit code 2 indicates error


if __name__ == "__main__":
    sys.exit(main())
