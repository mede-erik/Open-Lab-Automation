# Error Codes - Open Lab Automation

## Error Code Format

All error codes follow the standardized format:

```
[RESOURCE-XXX]
```

Where:
- **RESOURCE**: 3-4 letter abbreviation identifying the resource/component (e.g., VISA, FILE, DB, NET, VALID)
- **XXX**: Three-digit progressive number uniquely identifying the error within that resource

## Format in Logs

In log files, codes appear without square brackets:

```
[Timestamp] LEVEL-CODE-Message
[11:20:08] ERROR-VISA-002-Cannot open device at TCPIP0::192.168.1.104::INSTR
```

---

## VISA - Instrument Communication Errors (VISA-XXX)

Errors related to VISA (Virtual Instrument Software Architecture) communication with measurement instruments.

### VISA-001: VISA Connection Failed
**Description**: Unable to establish VISA connection with instrument  
**Common Cause**: 
- Instrument powered off
- Network cable disconnected
- Incorrect IP address
- Firewall blocking the port

**Solution**:
1. Verify that the instrument is powered on
2. Check network connection
3. Verify VISA address in settings
4. Check firewall settings

**Log Example**:
```
[10:30:45] ERROR-VISA-001-Connection failed to TCPIP0::192.168.1.100::INSTR
```

---

### VISA-002: VISA Resource Not Found
**Description**: VISA resource not found or unavailable  
**Common Cause**:
- Instrument not present on network
- Invalid VISA address
- VISA drivers not installed

**Solution**:
1. Verify that the instrument is reachable (ping the IP)
2. Check VISA address syntax
3. Install/update NI-VISA or PyVISA-py drivers
4. Use VISA Resource Manager to scan devices

**Log Example**:
```
[10:31:12] ERROR-VISA-002-Resource not found at TCPIP0::192.168.1.104::INSTR
```

---

### VISA-003: VISA Communication Error
**Description**: Generic VISA communication error  
**Common Cause**:
- Communication interference
- SCPI command not supported
- Communication timeout

**Solution**:
1. Check network connection quality
2. Verify that SCPI command is correct for the model
3. Increase VISA timeout
4. Restart the instrument

**Log Example**:
```
[10:32:00] ERROR-VISA-003-Communication error during SCPI command
```

---

### VISA-004: VISA Timeout Error
**Description**: Timeout during VISA communication  
**Common Cause**:
- Instrument taking too long to respond
- Command requiring long processing
- Overloaded network

**Solution**:
1. Increase timeout value in settings
2. Verify that the instrument is not busy
3. Check network load
4. Split long operations into shorter commands

**Log Example**:
```
[10:33:15] ERROR-VISA-004-Timeout waiting for instrument response
```

---

### VISA-005: PyVISA Not Available
**Description**: PyVISA is not available or not installed  
**Common Cause**:
- PyVISA not installed
- Incompatible Python version
- Missing VISA backend

**Solution**:
1. Install PyVISA: `pip install pyvisa pyvisa-py`
2. Verify Python version (>= 3.8)
3. Install backend: `pip install pyvisa-py` (software) or NI-VISA (hardware)

**Log Example**:
```
[10:34:00] ERROR-VISA-005-PyVISA library not available
```

---

## FILE - File System Errors (FILE-XXX)

Errors related to file access and manipulation.

### FILE-001: File Not Found
**Description**: Requested file not found  
**Common Cause**:
- File moved or deleted
- Incorrect file path
- Missing project file

**Solution**:
1. Verify that the file exists in the specified path
2. Check folder access permissions
3. Recreate the file if necessary
4. Verify path in project file

**Log Example**:
```
[10:35:00] ERROR-FILE-001-Configuration file not found: /path/to/config.json
```

---

### FILE-002: File Access Denied
**Description**: File access denied  
**Common Cause**:
- Insufficient permissions
- File in use by another process
- File in protected folder

**Solution**:
1. Run application with appropriate permissions
2. Close programs that might be locking the file
3. Verify file permissions: `chmod` (Linux) or Properties (Windows)
4. Move file to accessible folder

**Log Example**:
```
[10:36:00] ERROR-FILE-002-Access denied to file: /root/protected.json
```

---

### FILE-003: File Corrupt
**Description**: File corrupted or damaged  
**Common Cause**:
- Interrupted write
- Damaged disk
- Incorrect manual modification

**Solution**:
1. Restore from backup if available
2. Try to repair the file (if JSON, verify syntax)
3. Recreate the file from scratch
4. Check disk integrity

**Log Example**:
```
[10:37:00] ERROR-FILE-003-Corrupted file detected: project.json
```

---

### FILE-004: File Invalid Format
**Description**: Invalid file format  
**Common Cause**:
- Malformed JSON
- Missing required fields
- Incorrect data structure

**Solution**:
1. Validate JSON with online parser (jsonlint.com)
2. Verify required data structure
3. Check file encoding (UTF-8)
4. Regenerate file from interface

**Log Example**:
```
[10:38:00] ERROR-FILE-004-Invalid JSON format in instruments.inst
```

---

## VALID - Data Validation Errors (VALID-XXX)

User input validation errors.

### VALID-001: Invalid Email
**Description**: Invalid email format  
**Common Cause**:
- Email without @
- Invalid domain
- Special characters not allowed

**Solution**:
1. Verify format: `user@domain.ext`
2. Check special characters
3. Use valid email

**Log Example**:
```
[10:39:00] ERROR-VALID-001-Invalid email format: user@invalid
```

---

### VALID-002: Invalid IP Address
**Description**: Invalid IP address  
**Common Cause**:
- Incorrect IP format
- Octets out of range (0-255)
- Incomplete IP

**Solution**:
1. Verify format: `XXX.XXX.XXX.XXX`
2. Check that each octet is 0-255
3. Use only numbers and dots

**Log Example**:
```
[10:40:00] ERROR-VALID-002-Invalid IP address: 192.168.1.999
```

---

### VALID-003: Invalid Port
**Description**: Invalid port number  
**Common Cause**:
- Port out of range (1-65535)
- Reserved port
- Port already in use

**Solution**:
1. Use port in range 1024-65535 (non-reserved)
2. Verify that the port is not in use
3. Check firewall

**Log Example**:
```
[10:41:00] ERROR-VALID-003-Invalid port number: 99999
```

---

### VALID-004: Empty Field
**Description**: Required field empty  
**Common Cause**:
- User did not fill required field
- Field accidentally cleared

**Solution**:
1. Fill all required fields (marked with *)
2. Verify that values are not just spaces

**Log Example**:
```
[10:42:00] ERROR-VALID-004-Required field is empty: instrument_name
```

---

### VALID-005: Out of Range
**Description**: Value out of allowed range  
**Common Cause**:
- Value too high or low
- Instrument range exceeded

**Solution**:
1. Verify min/max field limits
2. Consult instrument datasheet for limits
3. Use value within allowed range

**Log Example**:
```
[10:43:00] ERROR-VALID-005-Voltage out of range: 150V (max: 100V)
```

---

### VALID-006: Invalid Format
**Description**: Generic invalid data format  
**Common Cause**:
- Incorrect date format
- Incorrect numeric format
- Characters not allowed

**Solution**:
1. Verify required field format
2. Use correct separators (. vs ,)
3. Check date/time format

**Log Example**:
```
[10:44:00] ERROR-VALID-006-Invalid date format: 32/13/2025 (expected: DD/MM/YYYY)
```

---

## DB - Database Errors (DB-XXX)

Errors related to database access.

### DB-001: Database Connection Error
**Description**: Unable to connect to database  
**Common Cause**:
- Database server not running
- Incorrect credentials
- Incorrect database address

**Solution**:
1. Verify that the database is active
2. Check username/password
3. Verify connection string
4. Check database firewall

**Log Example**:
```
[10:45:00] ERROR-DB-001-Cannot connect to database at localhost:5432
```

---

### DB-002: Database Query Error
**Description**: Error during query execution  
**Common Cause**:
- Malformed SQL query
- Non-existent table
- Insufficient permissions

**Solution**:
1. Verify SQL syntax
2. Check that tables/columns exist
3. Verify database user permissions

**Log Example**:
```
[10:46:00] ERROR-DB-002-Query failed: SELECT * FROM non_existing_table
```

---

### DB-003: Database Timeout
**Description**: Timeout during database operation  
**Common Cause**:
- Query too complex
- Overloaded database
- Slow connection

**Solution**:
1. Optimize query
2. Increase connection timeout
3. Add indexes to tables
4. Check database load

**Log Example**:
```
[10:47:00] ERROR-DB-003-Database query timeout after 30s
```

---

## NET - Network Errors (NET-XXX)

Generic network errors.

### NET-001: Connection Timeout
**Description**: Network connection timeout  
**Common Cause**:
- Server not responding
- Overloaded network
- Firewall blocking connection

**Solution**:
1. Verify internet connection
2. Ping remote host
3. Check firewall settings
4. Increase timeout

**Log Example**:
```
[10:48:00] ERROR-NET-001-Connection timeout to api.server.com
```

---

### NET-002: Host Unreachable
**Description**: Host unreachable  
**Common Cause**:
- Incorrect IP
- Host offline
- Incorrect routing

**Solution**:
1. Verify host address
2. Ping the host: `ping hostname`
3. Check routing table
4. Verify network connection

**Log Example**:
```
[10:49:00] ERROR-NET-002-Host unreachable: 192.168.1.250
```

---

### NET-003: DNS Error
**Description**: DNS resolution error  
**Common Cause**:
- DNS server not responding
- Incorrect domain name
- DNS provider issues

**Solution**:
1. Verify domain name
2. Check DNS settings
3. Use public DNS (8.8.8.8, 1.1.1.1)
4. Flush DNS cache

**Log Example**:
```
[10:50:00] ERROR-NET-003-DNS resolution failed for invalid.domain.xyz
```

---

## UI - User Interface Errors (UI-XXX)

Errors related to graphical interface.

### UI-001: Widget Deleted
**Description**: UI widget deleted during operation  
**Common Cause**:
- Widget destroyed before operation completion
- Timer accessing deleted widget
- Window closed during process

**Solution**:
1. Do not close windows during operations
2. Wait for process completion
3. Restart application if necessary

**Log Example**:
```
[10:51:00] ERROR-UI-001-Widget deleted during operation: ConnectionButton
```

---

### UI-002: Invalid UI State
**Description**: Invalid UI state  
**Common Cause**:
- Operation in unexpected state
- Inconsistent UI data
- Application logic bug

**Solution**:
1. Restart application
2. Reload project
3. Report bug if it persists

**Log Example**:
```
[10:52:00] ERROR-UI-002-Invalid state: project loaded but no instruments
```

---

### UI-003: Timer Error
**Description**: UI timer error  
**Common Cause**:
- Active timer on deleted widget
- Invalid timer interval
- Too many active timers

**Solution**:
1. Stop timers before closing windows
2. Verify timer interval
3. Limit number of active timers

**Log Example**:
```
[10:53:00] ERROR-UI-003-Timer error: cannot start timer on deleted widget
```

---

## DL - Datalogger Configuration Errors (DL-XXX)

Errors related to datalogger slot and module configuration.

### DL-001: No Slots Configured
**Description**: Datalogger has no slots configured  
**Common Cause**:
- Datalogger model without slot information in library
- Incorrect library configuration
- Model capabilities missing

**Solution**:
1. Verify that the datalogger model supports slots
2. Check `instruments_lib.json` for `number_of_slots` in capabilities
3. Update library if necessary
4. Contact support if model should have slots

**Log Example**:
```
[11:00:00] ERROR-DL-001-Datalogger Keysight_34972A has no slots configured
```

---

### DL-002: Invalid Module
**Description**: Selected module is invalid  
**Common Cause**:
- Module ID does not exist
- Malformed module ID
- Library corruption

**Solution**:
1. Verify module ID syntax
2. Check that module exists in `datalogger_modules` section
3. Reload instrument library
4. Recreate configuration

**Log Example**:
```
[11:01:00] ERROR-DL-002-Invalid module selected: 34999X
```

---

### DL-003: Incompatible Module
**Description**: Module not compatible with this datalogger  
**Common Cause**:
- Module not in `compatible_modules` list
- Wrong module for different datalogger series
- Incorrect library configuration

**Solution**:
1. Check `compatible_modules` list in datalogger capabilities
2. Select compatible module from dropdown
3. Consult datalogger manual for compatible modules
4. Update library if module should be compatible

**Log Example**:
```
[11:02:00] ERROR-DL-003-Module 34902A not compatible with datalogger model ODP3033
```

---

### DL-004: Module Not Found
**Description**: Module not found in instrument library  
**Common Cause**:
- Module not defined in `datalogger_modules` section
- Library incomplete or outdated
- Module ID typo

**Solution**:
1. Verify module exists in `instruments_lib.json`
2. Add module definition if missing
3. Update library from repository
4. Check module ID spelling

**Log Example**:
```
[11:03:00] ERROR-DL-004-Module 34901A not found in library
```

---

### DL-005: Empty Slot
**Description**: Attempted operation on empty slot  
**Common Cause**:
- No module configured for slot
- Trying to read from unconfigured slot
- Configuration error

**Solution**:
1. Configure module for the slot before using it
2. Enable at least one module
3. Verify slot configuration in dialog

**Log Example**:
```
[11:04:00] ERROR-DL-005-Slot 2 is empty, cannot configure channels
```

---

### DL-006: Module Disabled
**Description**: Module is disabled in library  
**Common Cause**:
- Module has `not_enabled: true` in library
- Module under development or deprecated
- Experimental module

**Solution**:
1. Check library: module may have `"not_enabled": true`
2. Remove `not_enabled` flag if module is ready
3. Select different module that is enabled
4. Contact support for module enablement

**Log Example**:
```
[11:05:00] ERROR-DL-006-Module 34903A is disabled in library
```

---

### DL-007: Invalid Slot Number
**Description**: Slot number out of range  
**Common Cause**:
- Slot number exceeds available slots
- Slot number less than 1
- Programming error

**Solution**:
1. Use slot numbers from 1 to number_of_slots
2. Verify datalogger slot count in library
3. Report bug if error persists

**Log Example**:
```
[11:06:00] ERROR-DL-007-Invalid slot number: 5 (max: 3)
```

---

### DL-008: Configuration Error
**Description**: General datalogger configuration error  
**Common Cause**:
- Corrupted configuration data
- Missing required fields
- Inconsistent slot/module data

**Solution**:
1. Recreate datalogger configuration
2. Check configuration file syntax
3. Clear and reconfigure all slots
4. Contact support if issue persists

**Log Example**:
```
[11:07:00] ERROR-DL-008-Configuration error: missing channels for slot 1
```

---

## TOOL - Tool Errors (TOOL-XXX)

### TOOL-001: No Instrument Selected
**Description**: No instrument selected for tool operation  
**Common Cause**:
- Tool opened without selecting an instrument
- Project has no compatible instruments
- Instrument selection cleared

**Solution**:
1. Select an electronic load from the dropdown
2. Verify project has configured instruments
3. Check .inst file contains electronic loads
4. Add instruments to project if needed

**Log Example**:
```
[12:00:00] ERROR-TOOL-001-No instrument selected for pulse generation
```

---

### TOOL-002: Instrument Not Found
**Description**: Selected instrument not found in project configuration  
**Common Cause**:
- Instrument removed from project
- Configuration file corrupted
- Project file mismatch

**Solution**:
1. Verify instrument exists in .inst file
2. Reload project
3. Re-add instrument if necessary
4. Check project file integrity

**Log Example**:
```
[12:01:00] ERROR-TOOL-002-Instrument EL_Load_1 not found in project
```

---

### TOOL-003: Missing Required Commands
**Description**: Required SCPI commands not found in instrument library  
**Common Cause**:
- Instrument library incomplete
- Model does not support pulse/dynamic mode
- Library not updated
- Wrong instrument type selected

**Solution**:
1. Check instruments_lib.json for required commands
2. Add missing commands: `set_dynamic_level_high`, `set_dynamic_level_low`, `load_on`, `load_off`
3. Consult instrument programming manual for correct SCPI syntax
4. Update library from repository
5. **NEVER attempt undefined commands - risk of instrument damage**

**Log Example**:
```
[12:02:00] ERROR-TOOL-003-Missing commands: set_dynamic_level_high, set_dynamic_level_low
```

---

### TOOL-004: Parameter Exceeds Limit
**Description**: Input parameter exceeds maximum safe limit from capabilities  
**Common Cause**:
- User entered value beyond instrument capability
- Amplitude > max_current_a
- Voltage > max_voltage_v
- Invalid parameter range

**Solution**:
1. Value automatically corrected to maximum
2. Check instrument capabilities in library
3. Use values within specified limits
4. Consult instrument manual for ratings

**Log Example**:
```
[12:03:00] ERROR-TOOL-004-Amplitude 50.0A exceeds maximum 40.0A. Corrected to 40.0A
```

---

### TOOL-005: Command Failed
**Description**: SCPI command execution failed  
**Common Cause**:
- VISA communication timeout
- Instrument not responding
- Command syntax error
- Instrument in wrong state

**Solution**:
1. Check VISA connection
2. Verify instrument powered on
3. Test with *IDN? query
4. Check command syntax in library
5. Restart instrument if necessary

**Log Example**:
```
[12:04:00] ERROR-TOOL-005-Command failed: set_dynamic_level_high - Timeout
```

---

### TOOL-006: Pulse Already Running
**Description**: Cannot start pulse while already running  
**Common Cause**:
- Start button pressed while pulse active
- Previous pulse not stopped properly
- State synchronization issue

**Solution**:
1. Stop current pulse before starting new one
2. Use Stop button to terminate pulse
3. Restart tool if state inconsistent
4. Check instrument output state

**Log Example**:
```
[12:05:00] ERROR-TOOL-006-Pulse already running. Stop before restarting
```

---

### TOOL-007: Missing Capabilities
**Description**: Instrument capabilities not defined in library  
**Common Cause**:
- Incomplete library entry
- Missing max_current_a, max_voltage_v, max_power_w
- New instrument not fully configured
- Library corruption

**Solution**:
1. Add complete capabilities to instruments_lib.json
2. Required fields: `max_current_a`, `max_voltage_v`, `max_power_w`
3. Consult instrument datasheet for correct values
4. Tool cannot validate safety limits without capabilities
5. **DO NOT use tool without safety limits defined**

**Log Example**:
```
[12:06:00] ERROR-TOOL-007-Missing capabilities for EL_Keysight_EL4913A
```

---

### TOOL-008: Power Exceeds Limit
**Description**: Combined power (I × V) exceeds max_power_w  
**Common Cause**:
- Amplitude and voltage combination too high
- P = I × V > max_power_w
- Parameter changed without power recalculation

**Solution**:
1. Last modified parameter automatically corrected
2. Reduce amplitude or voltage
3. Check power rating in capabilities
4. Calculate P = I × V before setting

**Log Example**:
```
[12:07:00] ERROR-TOOL-008-Power 2500W exceeds maximum 2000W
```

---

## How to Use This Guide

### For Users
1. **When an error occurs**: Note the error code shown in the log or message
2. **Search**: Find the code in this document (use Ctrl+F)
3. **Follow solution**: Apply proposed solutions step by step
4. **If problem persists**: Contact technical support with the error code

### For Developers
1. **Always use structured format**: `logger.error(msg, error_code="VISA-001")`
2. **Choose appropriate code**: Select the most specific error code
3. **Include context**: Add useful information to the message
4. **Update documentation**: Add new codes to this file when necessary

### For Technical Support
1. **Request error code**: Always ask the user for the complete code
2. **Check log**: View full application log for more context
3. **Follow solution path**: Use documented solutions as a guide
4. **Document new cases**: Update this guide with new scenarios

---

## Adding New Error Codes

To add a new error code:

1. **Choose appropriate category** (VISA, FILE, NET, etc.)
2. **Assign progressive number** (e.g. VISA-006)
3. **Update `errorhandler.py`**:
   ```python
   class ErrorCode(Enum):
       VISA_NEW_ERROR = "[VISA-006]"
   ```
4. **Document in this file** following existing format
5. **Test the new code** with `test_structured_logging.py`

---

## Category Summary

| Category | Range | Description |
|----------|-------|-------------|
| **VISA** | 001-099 | Instrument communication errors |
| **FILE** | 001-099 | File system errors |
| **VALID** | 001-099 | Input validation errors |
| **DB** | 001-099 | Database errors |
| **NET** | 001-099 | Generic network errors |
| **UI** | 001-099 | User interface errors |
| **DL** | 001-099 | Datalogger configuration errors |

---

## Version and Changelog

**Version**: 1.0  
**Date**: January 23, 2025  
**Author**: Open Lab Automation Team

### Changelog
- **v1.0** (January 23, 2025): First version with structured logging system
  - Added 24 initial error codes
  - Complete documentation for each code
  - Practical solutions for common problems

---

## Useful Links

- **Logging Guide**: `STRUCTURED_LOGGING_GUIDE.md`
- **Implementation**: `STRUCTURED_LOGGING_IMPLEMENTATION.md`
- **Test Suite**: `test_structured_logging.py`
- **Error Handler**: `frontend/core/errorhandler.py`
- **Logger**: `frontend/core/logger.py`

---

*Document updated on: January 23, 2025*
