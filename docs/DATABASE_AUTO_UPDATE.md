# Automatic Database Updates on Startup

## Overview

Opey II includes an automatic database update system that monitors OBP (Open Bank Project) data for changes and updates the vector database when changes are detected. This ensures that the application always has the latest glossary terms and API endpoint documentation without manual intervention.

## How It Works

### 1. Data Hash Management

The system uses SHA-256 hashing to detect changes in OBP data:

- **Glossary Data**: All glossary items are fetched from the OBP API and hashed
- **Endpoint Data**: All API endpoint documentation is fetched from the OBP Swagger docs and hashed
- **Hash Storage**: Hashes are stored in `.obp_data_hashes.json` at the project root

### 2. Startup Check Process

When the application starts (if enabled):

1. **Fetch Current Data**: Downloads the latest glossary and endpoint data from OBP
2. **Compute Hashes**: Calculates SHA-256 hashes of the fetched data
3. **Compare**: Compares current hashes with stored hashes from previous import
4. **Update Decision**: If hashes differ, triggers a database rebuild
5. **Update Storage**: After successful update, saves new hashes for future comparisons

### 3. Database Population

When changes are detected, the system:

1. Runs the `populate_vector_db.py` script automatically
2. Processes glossary and endpoint data with schema validation
3. Populates the vector database with updated documents
4. Updates the stored hash file upon successful completion

## Configuration

### Environment Variables

Add these to your `.env` file:

```bash
# Enable/disable automatic database updates on startup
UPDATE_DATABASE_ON_STARTUP="false"  # Set to "true" to enable

# Type of endpoints to include
UPDATE_DATABASE_ENDPOINT_TYPE="all"  # Options: "static", "dynamic", "all"
```

### Configuration Options

#### `UPDATE_DATABASE_ON_STARTUP`

Controls whether the automatic update check runs on application startup.

- **Values**: `true`, `false`, `1`, `0`, `yes`, `no`, `on`, `off` (case-insensitive)
- **Default**: `false`
- **Recommended**: 
  - `true` for production environments to ensure data freshness
  - `false` for local development to speed up startup

#### `UPDATE_DATABASE_ENDPOINT_TYPE`

Specifies which types of OBP endpoints to include in the database.

- **Values**: 
  - `static`: Only standard OBP API endpoints
  - `dynamic`: Only dynamic entity endpoints
  - `all`: Both static and dynamic endpoints
- **Default**: `all`
- **Recommended**: `all` for complete API coverage

## Usage

### Enable Automatic Updates

1. Edit your `.env` file:
   ```bash
   UPDATE_DATABASE_ON_STARTUP="true"
   UPDATE_DATABASE_ENDPOINT_TYPE="all"
   ```

2. Start the application normally:
   ```bash
   python src/run_service.py
   ```

3. Watch the logs during startup:
   ```
   INFO - Checking OBP data for updates...
   INFO - Fetching OBP data from: https://...
   INFO - Computed hashes - Glossary: abc12345..., Endpoints: def67890...
   INFO - Changes detected in: glossary, endpoints
   INFO - Starting database update...
   INFO - Running populate script with endpoint_type: all
   INFO - Database population completed successfully
   INFO - Stored hashes updated successfully
   INFO - ✓ Database update completed and hashes updated
   ```

### Skip Updates (Faster Startup)

For development when you don't need the latest data:

```bash
UPDATE_DATABASE_ON_STARTUP="false"
```

The application will start immediately without checking for updates.

### Manual Update

You can still manually update the database using the populate script:

```bash
python src/database/populate_vector_db.py --endpoints all
```

After a manual update, the hash file will be automatically updated on the next startup check.

## Files and Locations

### Hash Storage File

- **Location**: `.obp_data_hashes.json` (project root)
- **Format**: JSON file containing glossary and endpoint hashes
- **Git**: Excluded via `.gitignore` (environment-specific)

Example content:
```json
{
  "glossary": "a1b2c3d4e5f6...",
  "endpoints": "f6e5d4c3b2a1...",
  "endpoint_type": "all"
}
```

### Source Files

- **Hash Manager**: `src/database/data_hash_manager.py`
- **Startup Updater**: `src/database/startup_updater.py`
- **Lifecycle Integration**: `src/service/lifecycle.py`
- **Population Script**: `src/database/populate_vector_db.py`

## Behavior Details

### First Startup

On the first startup after enabling this feature:
- No hash file exists
- System detects this as "needs update"
- Automatically populates the database
- Creates the hash file for future comparisons

### Subsequent Startups

On later startups:
- Loads existing hash file
- Fetches current OBP data
- Compares hashes
- Only updates if changes detected

### Update Failures

If database update fails:
- Error is logged
- Application continues with existing database
- Hash file remains unchanged
- Next startup will retry the update

### Network Issues

If OBP API is unreachable during startup:
- Error is logged
- Application continues with existing database
- Update will be retried on next startup

## Performance Considerations

### Startup Time Impact

With `UPDATE_DATABASE_ON_STARTUP="true"`:
- **Hash check**: ~2-5 seconds (network dependent)
- **Database update** (if needed): ~30-60 seconds
- **No update needed**: ~2-5 seconds

With `UPDATE_DATABASE_ON_STARTUP="false"`:
- **No impact**: Immediate startup

### Recommendations

- **Production**: Enable updates to ensure data freshness
- **Development**: Disable updates for faster iteration
- **CI/CD**: Enable updates in deployment pipeline
- **Testing**: Disable updates to ensure consistent test data

## Monitoring and Logging

### Log Messages

The system provides detailed logging at various stages:

```
INFO - Database check/update completed successfully
⚠ Changes detected in: glossary, endpoints
✓ Database is up to date - no update needed
✗ Database update failed
```

### Error Handling

All errors are logged with full stack traces:
- Network errors when fetching OBP data
- Hash computation errors
- Database population failures
- File I/O errors

## Troubleshooting

### Issue: Updates Not Running

**Check:**
1. Is `UPDATE_DATABASE_ON_STARTUP` set to `true`?
2. Are `OBP_BASE_URL` and `OBP_API_VERSION` configured?
3. Check logs for error messages

### Issue: Update Takes Too Long

**Solutions:**
1. Use `UPDATE_DATABASE_ENDPOINT_TYPE="static"` instead of "all"
2. Disable updates for development: `UPDATE_DATABASE_ON_STARTUP="false"`
3. Check network connectivity to OBP API

### Issue: Hash File Missing

**Resolution:**
- File is auto-created on first successful update
- Manually delete `.obp_data_hashes.json` to force a full update

### Issue: False Change Detection

**Possible Causes:**
- OBP API returns data in different order (should not happen due to sorted hashing)
- Endpoint type changed in configuration
- Manual modification of hash file

**Resolution:**
- Delete `.obp_data_hashes.json` and restart
- System will rebuild hash from current data

## Best Practices

1. **Production Deployment**: Always enable automatic updates
2. **Version Control**: Never commit `.obp_data_hashes.json` 
3. **Monitoring**: Watch startup logs for update status
4. **Testing**: Use separate hash files for different environments
5. **Maintenance**: Periodically verify database contents match OBP API

## Integration with Existing Workflows

### Manual Population Script

The existing `populate_vector_db.py` script continues to work independently:

```bash
# Still works as before
python src/database/populate_vector_db.py --endpoints all
```

### Automated Updates Complement Manual Updates

- Automatic updates run on startup (if enabled)
- Manual script can be run anytime
- Both methods update the hash file
- No conflicts between methods

## Future Enhancements

Potential improvements for consideration:

1. **Scheduled Updates**: Background task to check periodically (not just startup)
2. **Selective Updates**: Update only changed collections (glossary OR endpoints)
3. **Update Notifications**: Alert users when database is updated
4. **Hash History**: Track when and what changed over time
5. **Rollback Support**: Restore previous database version if needed

## Security Considerations

- Hash file contains no sensitive data (only SHA-256 hashes)
- OBP data is public API documentation
- No authentication required for hash checks
- Update process runs with application privileges
- Network requests use standard HTTPS

## Summary

The automatic database update system provides:

✅ **Fresh Data**: Always use latest OBP documentation  
✅ **Automatic**: No manual intervention required  
✅ **Efficient**: Only updates when changes detected  
✅ **Configurable**: Easy to enable/disable per environment  
✅ **Resilient**: Continues on failure, retries on next startup  
✅ **Observable**: Detailed logging for monitoring  

Enable it in production to ensure your Opey instance always has the most current OBP API documentation.
