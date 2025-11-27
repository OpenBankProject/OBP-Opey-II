"""
Tests for the database auto-update system.
"""

import pytest
import json
import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from src.database.data_hash_manager import DataHashManager
from src.database.startup_updater import DatabaseStartupUpdater


@pytest.fixture
def temp_hash_file(tmp_path):
    """Create a temporary hash file for testing."""
    hash_file = tmp_path / ".obp_data_hashes.json"
    return str(hash_file)


@pytest.fixture
def mock_obp_config(monkeypatch):
    """Set up mock OBP configuration."""
    monkeypatch.setenv("OBP_BASE_URL", "https://test.openbankproject.com")
    monkeypatch.setenv("OBP_API_VERSION", "v5.0.0")


class TestDataHashManager:
    """Tests for DataHashManager class."""
    
    def test_init_with_env_vars(self, mock_obp_config, temp_hash_file):
        """Test initialization with environment variables."""
        manager = DataHashManager(temp_hash_file)
        assert manager.base_url == "https://test.openbankproject.com"
        assert manager.api_version == "v5.0.0"
        assert str(manager.hash_storage_path) == temp_hash_file
    
    def test_init_without_env_vars(self, temp_hash_file, monkeypatch):
        """Test initialization fails without required env vars."""
        monkeypatch.delenv("OBP_BASE_URL", raising=False)
        monkeypatch.delenv("OBP_API_VERSION", raising=False)
        
        with pytest.raises(ValueError, match="OBP_BASE_URL and OBP_API_VERSION"):
            DataHashManager(temp_hash_file)
    
    def test_compute_hash(self, mock_obp_config, temp_hash_file):
        """Test hash computation is consistent."""
        manager = DataHashManager(temp_hash_file)
        
        data1 = {"key": "value", "number": 123}
        data2 = {"number": 123, "key": "value"}  # Different order
        
        hash1 = manager._compute_hash(data1)
        hash2 = manager._compute_hash(data2)
        
        # Should be identical despite different key order
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 produces 64 hex chars
    
    def test_save_and_load_hashes(self, mock_obp_config, temp_hash_file):
        """Test saving and loading hash data."""
        manager = DataHashManager(temp_hash_file)
        
        test_hashes = {
            "glossary": "abc123",
            "endpoints": "def456",
            "endpoint_type": "all"
        }
        
        # Save hashes
        manager.save_hashes(test_hashes)
        
        # Load hashes
        loaded = manager.load_stored_hashes()
        
        assert loaded == test_hashes
    
    def test_load_nonexistent_hashes(self, mock_obp_config, temp_hash_file):
        """Test loading when hash file doesn't exist."""
        manager = DataHashManager(temp_hash_file)
        loaded = manager.load_stored_hashes()
        assert loaded is None
    
    def test_compare_hashes_no_stored(self, mock_obp_config, temp_hash_file):
        """Test comparison when no stored hashes exist."""
        manager = DataHashManager(temp_hash_file)
        
        current = {"glossary": "abc", "endpoints": "def"}
        needs_update, changes = manager.compare_hashes(current, None)
        
        assert needs_update is True
        assert changes["glossary"] is True
        assert changes["endpoints"] is True
    
    def test_compare_hashes_no_changes(self, mock_obp_config, temp_hash_file):
        """Test comparison when data hasn't changed."""
        manager = DataHashManager(temp_hash_file)
        
        hashes = {"glossary": "abc", "endpoints": "def"}
        needs_update, changes = manager.compare_hashes(hashes, hashes)
        
        assert needs_update is False
        assert changes["glossary"] is False
        assert changes["endpoints"] is False
    
    def test_compare_hashes_glossary_changed(self, mock_obp_config, temp_hash_file):
        """Test comparison when only glossary changed."""
        manager = DataHashManager(temp_hash_file)
        
        current = {"glossary": "new_hash", "endpoints": "def"}
        stored = {"glossary": "old_hash", "endpoints": "def"}
        
        needs_update, changes = manager.compare_hashes(current, stored)
        
        assert needs_update is True
        assert changes["glossary"] is True
        assert changes["endpoints"] is False
    
    def test_compare_hashes_endpoints_changed(self, mock_obp_config, temp_hash_file):
        """Test comparison when only endpoints changed."""
        manager = DataHashManager(temp_hash_file)
        
        current = {"glossary": "abc", "endpoints": "new_hash"}
        stored = {"glossary": "abc", "endpoints": "old_hash"}
        
        needs_update, changes = manager.compare_hashes(current, stored)
        
        assert needs_update is True
        assert changes["glossary"] is False
        assert changes["endpoints"] is True
    
    @patch('src.database.data_hash_manager.requests.get')
    def test_fetch_obp_data_success(self, mock_get, mock_obp_config, temp_hash_file):
        """Test successful data fetch from OBP."""
        manager = DataHashManager(temp_hash_file)
        
        mock_response = Mock()
        mock_response.json.return_value = {"test": "data"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        result = manager._fetch_obp_data("https://test.com/api")
        
        assert result == {"test": "data"}
        mock_get.assert_called_once()
    
    @patch('src.database.data_hash_manager.requests.get')
    def test_fetch_obp_data_failure(self, mock_get, mock_obp_config, temp_hash_file):
        """Test handling of fetch failure."""
        manager = DataHashManager(temp_hash_file)
        
        mock_get.side_effect = Exception("Network error")
        
        with pytest.raises(Exception, match="Network error"):
            manager._fetch_obp_data("https://test.com/api")


class TestDatabaseStartupUpdater:
    """Tests for DatabaseStartupUpdater class."""
    
    def test_init_default_endpoint_type(self, mock_obp_config, monkeypatch):
        """Test initialization with default endpoint type."""
        monkeypatch.setenv("UPDATE_DATABASE_ENDPOINT_TYPE", "static")
        updater = DatabaseStartupUpdater()
        assert updater.endpoint_type == "static"
    
    def test_init_custom_endpoint_type(self, mock_obp_config):
        """Test initialization with custom endpoint type."""
        updater = DatabaseStartupUpdater(endpoint_type="dynamic")
        assert updater.endpoint_type == "dynamic"
    
    def test_init_invalid_endpoint_type(self, mock_obp_config):
        """Test initialization with invalid endpoint type defaults to 'all'."""
        updater = DatabaseStartupUpdater(endpoint_type="invalid")
        assert updater.endpoint_type == "all"
    
    @pytest.mark.parametrize("env_value,expected", [
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("no", False),
        ("", False),
    ])
    def test_should_update_on_startup(self, mock_obp_config, monkeypatch, env_value, expected):
        """Test parsing of UPDATE_DATABASE_ON_STARTUP flag."""
        monkeypatch.setenv("UPDATE_DATABASE_ON_STARTUP", env_value)
        updater = DatabaseStartupUpdater()
        assert updater.should_update_on_startup() == expected
    
    @patch('src.database.startup_updater.subprocess.run')
    def test_run_populate_script_success(self, mock_run, mock_obp_config):
        """Test successful execution of populate script."""
        mock_run.return_value = Mock(returncode=0, stdout="Success", stderr="")
        
        updater = DatabaseStartupUpdater()
        result = updater.run_populate_script()
        
        assert result is True
        mock_run.assert_called_once()
    
    @patch('src.database.startup_updater.subprocess.run')
    def test_run_populate_script_failure(self, mock_run, mock_obp_config):
        """Test handling of populate script failure."""
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="Error")
        
        updater = DatabaseStartupUpdater()
        result = updater.run_populate_script()
        
        assert result is False
    
    @patch.object(DatabaseStartupUpdater, 'should_update_on_startup')
    def test_check_and_update_disabled(self, mock_should_update, mock_obp_config):
        """Test check_and_update when feature is disabled."""
        mock_should_update.return_value = False
        
        updater = DatabaseStartupUpdater()
        result = updater.check_and_update()
        
        assert result is True
        mock_should_update.assert_called_once()
    
    @patch.object(DatabaseStartupUpdater, 'should_update_on_startup')
    @patch.object(DatabaseStartupUpdater, 'run_populate_script')
    def test_check_and_update_no_changes(self, mock_run_script, mock_should_update, 
                                        mock_obp_config, temp_hash_file):
        """Test check_and_update when no changes detected."""
        mock_should_update.return_value = True
        
        with patch.object(DataHashManager, 'check_for_updates') as mock_check:
            mock_check.return_value = (False, {"glossary": False, "endpoints": False})
            
            updater = DatabaseStartupUpdater()
            result = updater.check_and_update()
            
            assert result is True
            mock_run_script.assert_not_called()
    
    @patch.object(DatabaseStartupUpdater, 'should_update_on_startup')
    @patch.object(DatabaseStartupUpdater, 'run_populate_script')
    @patch.object(DataHashManager, 'update_stored_hashes')
    def test_check_and_update_with_changes(self, mock_update_hashes, mock_run_script, 
                                          mock_should_update, mock_obp_config):
        """Test check_and_update when changes are detected."""
        mock_should_update.return_value = True
        mock_run_script.return_value = True
        
        with patch.object(DataHashManager, 'check_for_updates') as mock_check:
            mock_check.return_value = (True, {"glossary": True, "endpoints": False})
            
            updater = DatabaseStartupUpdater()
            result = updater.check_and_update()
            
            assert result is True
            mock_run_script.assert_called_once()
            mock_update_hashes.assert_called_once()
    
    @patch.object(DatabaseStartupUpdater, 'should_update_on_startup')
    @patch.object(DatabaseStartupUpdater, 'run_populate_script')
    def test_check_and_update_script_fails(self, mock_run_script, mock_should_update, 
                                          mock_obp_config):
        """Test check_and_update when populate script fails."""
        mock_should_update.return_value = True
        mock_run_script.return_value = False
        
        with patch.object(DataHashManager, 'check_for_updates') as mock_check:
            mock_check.return_value = (True, {"glossary": True, "endpoints": True})
            
            updater = DatabaseStartupUpdater()
            result = updater.check_and_update()
            
            assert result is False


@pytest.mark.asyncio
async def test_update_database_on_startup_async(mock_obp_config, monkeypatch):
    """Test async wrapper function."""
    from src.database.startup_updater import update_database_on_startup
    
    monkeypatch.setenv("UPDATE_DATABASE_ON_STARTUP", "false")
    
    result = await update_database_on_startup()
    assert result is True
