"""
Module to handle database updates on application startup.

This module checks for OBP data changes and updates the vector database
if changes are detected.
"""

import os
import sys
import logging
import subprocess
from typing import Optional
from pathlib import Path

from .data_hash_manager import DataHashManager

logger = logging.getLogger(__name__)


class DatabaseStartupUpdater:
    """Manages database updates during application startup."""
    
    def __init__(self, endpoint_type: Optional[str] = None):
        """
        Initialize the DatabaseStartupUpdater.
        
        Args:
            endpoint_type: Type of endpoints to include ("static", "dynamic", or "all").
                          Defaults to value from UPDATE_DATABASE_ENDPOINT_TYPE env var,
                          or "all" if not set.
        """
        self.hash_manager = DataHashManager()
        self.endpoint_type = endpoint_type or os.getenv("UPDATE_DATABASE_ENDPOINT_TYPE", "all")
        
        if self.endpoint_type not in ["static", "dynamic", "all"]:
            logger.warning(f"Invalid endpoint_type '{self.endpoint_type}', defaulting to 'all'")
            self.endpoint_type = "all"
    
    def should_update_on_startup(self) -> bool:
        """
        Check if database updates on startup are enabled.
        
        Returns:
            True if UPDATE_DATABASE_ON_STARTUP is set to 'true' (case-insensitive)
        """
        flag = os.getenv("UPDATE_DATABASE_ON_STARTUP", "false").lower()
        return flag in ["true", "1", "yes", "on"]
    
    def run_populate_script(self) -> bool:
        """
        Run the populate_vector_db.py script.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get the project root and script path
            project_root = Path(__file__).parent.parent.parent
            script_path = project_root / "src" / "database" / "populate_vector_db.py"
            
            if not script_path.exists():
                logger.error(f"Populate script not found at {script_path}")
                return False
            
            logger.info(f"Running populate script with endpoint_type: {self.endpoint_type}")
            
            # Run the script from the project root
            cmd = [sys.executable, str(script_path), "--endpoints", self.endpoint_type]
            
            result = subprocess.run(
                cmd,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode == 0:
                logger.info("Database population completed successfully")
                logger.debug(f"Script output: {result.stdout}")
                return True
            else:
                logger.error(f"Database population failed with exit code {result.returncode}")
                logger.error(f"Script error output: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("Database population timed out after 5 minutes")
            return False
        except Exception as e:
            logger.error(f"Error running populate script: {e}", exc_info=True)
            return False
    
    def check_and_update(self) -> bool:
        """
        Check for data changes and update database if needed.
        
        Returns:
            True if update was performed successfully, False otherwise.
            Returns True if no update was needed.
        """
        if not self.should_update_on_startup():
            logger.info("Database update on startup is disabled (UPDATE_DATABASE_ON_STARTUP=false)")
            return True
        
        logger.info("Checking for OBP data changes...")
        
        try:
            # Check if data has changed
            needs_update, changes = self.hash_manager.check_for_updates(self.endpoint_type)
            
            if not needs_update:
                logger.info("✓ Database is up to date - no update needed")
                return True
            
            # Log what changed
            changed_collections = [k for k, v in changes.items() if v]
            logger.info(f"⚠ Changes detected in: {', '.join(changed_collections)}")
            logger.info("Starting database update...")
            
            # Run the populate script
            success = self.run_populate_script()
            
            if success:
                # Update stored hashes
                self.hash_manager.update_stored_hashes(self.endpoint_type)
                logger.info("✓ Database update completed and hashes updated")
                return True
            else:
                logger.error("✗ Database update failed")
                return False
                
        except Exception as e:
            logger.error(f"Error during database update check: {e}", exc_info=True)
            return False


async def update_database_on_startup(endpoint_type: Optional[str] = None) -> bool:
    """
    Async wrapper for database update on startup.
    
    Args:
        endpoint_type: Type of endpoints to include ("static", "dynamic", or "all")
        
    Returns:
        True if update was successful or not needed, False if update failed
    """
    updater = DatabaseStartupUpdater(endpoint_type)
    return updater.check_and_update()
