import pytest
from unittest.mock import AsyncMock, MagicMock
from src.checkpointer.obp_checkpoint_saver import OBPCheckpointSaver

@pytest.mark.anyio
async def test_check_existing_setup_returns_true_when_entities_exist():
    # Mock the OBPClient
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "dynamic_entities": [
            {"OpeyCheckpoint": {}},
            {"OpeyCheckpointWrite": {}}
        ]
    }
    mock_client.get = AsyncMock(return_value=mock_response)
    
    # Create saver and test
    saver = OBPCheckpointSaver(client=mock_client)
    result = await saver._check_existing_setup()
    
    assert result is True
    mock_client.get.assert_called_once_with("/obp/v6.0.0/management/system-dynamic-entities")

@pytest.mark.anyio
async def test_check_existing_setup_returns_false_when_entities_missing():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.json.return_value = {"dynamic_entities": []}
    mock_client.get = AsyncMock(return_value=mock_response)
    
    saver = OBPCheckpointSaver(client=mock_client)
    result = await saver._check_existing_setup()
    
    assert result is False

@pytest.mark.anyio
async def test_check_existing_setup_raises_on_api_error():
    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=Exception("API Error"))
    
    saver = OBPCheckpointSaver(client=mock_client)
    
    with pytest.raises(RuntimeError, match="Error checking existing OBP setup"):
        await saver._check_existing_setup()