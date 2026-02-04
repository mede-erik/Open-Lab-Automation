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

## PROJ - Project Errors (PROJ-XXX)

Errors related to project file management and operations.

### PROJ-001: Project Not Found
**Description**: Requested project file not found  
**Common Cause**:
- Project file moved or deleted
- Incorrect project path
- Project never created

**Solution**:
1. Verify project file exists in specified path
2. Check recent projects list
3. Create new project if necessary
4. Verify file extension (.json)

**Log Example**:
```
[13:00:00] ERROR-PROJ-001-Project file not found: /path/to/project.json
```

---

### PROJ-002: Project Corrupt
**Description**: Project file is corrupted or damaged  
**Common Cause**:
- Interrupted save operation
- Disk error during write
- Manual file modification error
- Power failure during save

**Solution**:
1. Restore from backup if available
2. Check project file with JSON validator
3. Recreate project from scratch
4. Verify disk integrity

**Log Example**:
```
[13:01:00] ERROR-PROJ-002-Corrupted project file detected: my_project.json
```

---

### PROJ-003: Invalid Project Format
**Description**: Project file has invalid format or structure  
**Common Cause**:
- Wrong file version
- Missing required fields
- Incorrect data structure
- File from incompatible software

**Solution**:
1. Verify file is a valid project file
2. Check required fields: name, version, instruments
3. Migrate from old format if necessary
4. Create new project with correct structure

**Log Example**:
```
[13:02:00] ERROR-PROJ-003-Invalid project format: missing 'instruments' field
```

---

### PROJ-004: Project Save Failed
**Description**: Failed to save project file  
**Common Cause**:
- Disk full
- No write permissions
- File locked by another process
- Invalid characters in filename

**Solution**:
1. Check available disk space
2. Verify write permissions on folder
3. Close other programs accessing the file
4. Use valid filename without special characters

**Log Example**:
```
[13:03:00] ERROR-PROJ-004-Failed to save project: disk full
```

---

### PROJ-005: Project Load Failed
**Description**: Failed to load project file  
**Common Cause**:
- File permissions issue
- Corrupted file content
- Missing dependencies
- Incompatible encoding

**Solution**:
1. Check file read permissions
2. Validate JSON structure
3. Verify file encoding (UTF-8)
4. Check associated files (.inst, .eff, .was)

**Log Example**:
```
[13:04:00] ERROR-PROJ-005-Failed to load project: invalid JSON encoding
```

---

### PROJ-006: Incompatible Project Version
**Description**: Project created with incompatible software version  
**Common Cause**:
- Project from newer software version
- Project from deprecated version
- Breaking changes in format
- Missing migration path

**Solution**:
1. Update application to latest version
2. Use migration tool if available
3. Manually update project structure
4. Create new project and reconfigure

**Log Example**:
```
[13:05:00] ERROR-PROJ-006-Project version 2.0 incompatible with current 1.5
```

---

### PROJ-007: Missing Project Files
**Description**: Required project files are missing  
**Common Cause**:
- Associated files (.inst, .eff) deleted
- Files moved to different location
- Incomplete project copy
- Partial file extraction

**Solution**:
1. Verify all project files in same folder
2. Restore missing files from backup
3. Reconfigure missing components
4. Check project dependencies

**Log Example**:
```
[13:06:00] ERROR-PROJ-007-Missing required file: instruments.inst
```

---

### PROJ-008: Project Already Exists
**Description**: Attempt to create project with existing name  
**Common Cause**:
- Project name conflict
- Duplicate project creation
- Case-insensitive filesystem collision

**Solution**:
1. Choose different project name
2. Delete or rename existing project
3. Load existing project instead
4. Use unique naming convention

**Log Example**:
```
[13:07:00] ERROR-PROJ-008-Project 'TestProject' already exists
```

---

## INST - Instrument Configuration Errors (INST-XXX)

Errors related to instrument configuration and setup.

### INST-001: Instrument Not Supported
**Description**: Instrument model not supported by software  
**Common Cause**:
- Model not in library
- Instrument too new/old
- Experimental support disabled
- Wrong instrument type

**Solution**:
1. Check instruments_lib.json for model
2. Update instrument library
3. Add instrument manually to library
4. Contact support for new model support

**Log Example**:
```
[13:10:00] ERROR-INST-001-Instrument model XYZ123 not supported
```

---

### INST-002: Invalid Instrument Configuration
**Description**: Instrument configuration is invalid or incomplete  
**Common Cause**:
- Missing required parameters
- Invalid parameter values
- Incompatible settings combination
- Configuration file corrupted

**Solution**:
1. Verify all required fields filled
2. Check parameter value ranges
3. Review configuration for conflicts
4. Recreate instrument configuration

**Log Example**:
```
[13:11:00] ERROR-INST-002-Invalid configuration: missing VISA address
```

---

### INST-003: Duplicate Instrument
**Description**: Attempt to add instrument with duplicate ID or address  
**Common Cause**:
- Same VISA address used twice
- Duplicate instrument ID
- Copy/paste error
- Import conflict

**Solution**:
1. Use unique VISA address for each instrument
2. Assign unique instrument IDs
3. Remove duplicate before adding
4. Verify address not already in use

**Log Example**:
```
[13:12:00] ERROR-INST-003-Duplicate instrument at TCPIP0::192.168.1.100::INSTR
```

---

### INST-004: Invalid Instrument Type
**Description**: Specified instrument type is invalid  
**Common Cause**:
- Type not in allowed list
- Typo in type name
- Unsupported instrument category
- Configuration mismatch

**Solution**:
1. Use valid types: power_supply, datalogger, oscilloscope, electronic_load
2. Check spelling and case
3. Verify instrument category support
4. Update configuration with correct type

**Log Example**:
```
[13:13:00] ERROR-INST-004-Invalid instrument type: 'power_source'
```

---

### INST-005: Missing Instrument Parameters
**Description**: Required instrument parameters are missing  
**Common Cause**:
- Incomplete library entry
- Missing capabilities section
- No SCPI commands defined
- Partial configuration

**Solution**:
1. Add missing parameters to library
2. Define capabilities (channels, ranges, etc.)
3. Add required SCPI commands
4. Consult instrument datasheet

**Log Example**:
```
[13:14:00] ERROR-INST-005-Missing parameters: max_voltage, max_current
```

---

### INST-006: Instrument Connection Required
**Description**: Operation requires active instrument connection  
**Common Cause**:
- Instrument not connected
- Operation requires VISA session
- Offline mode active
- Connection lost

**Solution**:
1. Connect to instrument via VISA
2. Verify instrument powered on
3. Check network connection
4. Exit offline mode if active

**Log Example**:
```
[13:15:00] ERROR-INST-006-Connection required for remote operation
```

---

### INST-007: Instrument Not Initialized
**Description**: Instrument not properly initialized before use  
**Common Cause**:
- Missing initialization step
- Initialization failed previously
- Configuration not applied
- Reset required

**Solution**:
1. Initialize instrument before use
2. Check initialization logs for errors
3. Apply configuration settings
4. Reset and reinitialize if needed

**Log Example**:
```
[13:16:00] ERROR-INST-007-Instrument must be initialized before use
```

---

### INST-008: Incompatible Firmware Version
**Description**: Instrument firmware version incompatible  
**Common Cause**:
- Firmware too old
- Firmware too new
- Missing firmware features
- Known firmware bugs

**Solution**:
1. Update instrument firmware
2. Check minimum firmware requirements
3. Consult instrument manual for compatibility
4. Disable unsupported features

**Log Example**:
```
[13:17:00] ERROR-INST-008-Firmware v1.2.3 incompatible, requires >= v2.0.0
```

---

## CFG - Application Configuration Errors (CFG-XXX)

Errors related to application settings and configuration.

### CFG-001: Configuration File Missing
**Description**: Application configuration file not found  
**Common Cause**:
- First application run
- Config file deleted
- Installation incomplete
- Wrong working directory

**Solution**:
1. Create default configuration
2. Restore from backup
3. Reinstall application
4. Check working directory

**Log Example**:
```
[13:20:00] ERROR-CFG-001-Configuration file not found: config.json
```

---

### CFG-002: Invalid Configuration Value
**Description**: Configuration contains invalid value  
**Common Cause**:
- Manual file modification error
- Value out of range
- Wrong data type
- Corrupted setting

**Solution**:
1. Reset to default value
2. Edit configuration file manually
3. Use valid value range
4. Reset all settings if necessary

**Log Example**:
```
[13:21:00] ERROR-CFG-002-Invalid value for 'timeout': -5
```

---

### CFG-003: Incompatible Settings
**Description**: Configuration settings are incompatible  
**Common Cause**:
- Conflicting options enabled
- Mutually exclusive settings
- Resource conflict
- Logic error

**Solution**:
1. Review conflicting settings
2. Disable one of conflicting options
3. Check documentation for valid combinations
4. Reset to default configuration

**Log Example**:
```
[13:22:00] ERROR-CFG-003-Cannot enable both offline mode and auto-connect
```

---

### CFG-004: Configuration Parse Error
**Description**: Error parsing configuration file  
**Common Cause**:
- Malformed JSON
- Syntax error
- Invalid encoding
- Incomplete file

**Solution**:
1. Validate JSON with parser
2. Check for syntax errors (commas, brackets)
3. Verify UTF-8 encoding
4. Restore from backup or reset

**Log Example**:
```
[13:23:00] ERROR-CFG-004-Parse error at line 45: unexpected token
```

---

### CFG-005: Configuration Save Failed
**Description**: Failed to save configuration  
**Common Cause**:
- No write permissions
- Disk full
- File locked
- Path invalid

**Solution**:
1. Check write permissions
2. Free disk space
3. Close other programs
4. Verify config file path

**Log Example**:
```
[13:24:00] ERROR-CFG-005-Cannot save config: permission denied
```

---

### CFG-006: Configuration Load Failed
**Description**: Failed to load configuration  
**Common Cause**:
- File read error
- Corrupted file
- Invalid format
- Permission issue

**Solution**:
1. Check file permissions
2. Validate file integrity
3. Use default configuration
4. Recreate configuration file

**Log Example**:
```
[13:25:00] ERROR-CFG-006-Cannot load config: file corrupted
```

---

### CFG-007: Configuration Reset Required
**Description**: Configuration must be reset due to errors  
**Common Cause**:
- Multiple invalid settings
- Corrupted configuration
- Version migration failed
- Critical setting error

**Solution**:
1. Accept reset prompt
2. Backup current configuration
3. Reset to factory defaults
4. Reconfigure application settings

**Log Example**:
```
[13:26:00] ERROR-CFG-007-Configuration reset required due to critical errors
```

---

## LIB - Instrument Library Errors (LIB-XXX)

Errors related to the instrument library database.

### LIB-001: Library Not Found
**Description**: Instrument library file not found  
**Common Cause**:
- Library file deleted
- Wrong installation path
- Missing file in deployment
- Incorrect file reference

**Solution**:
1. Verify instruments_lib.json exists
2. Reinstall application
3. Download library from repository
4. Check file path in configuration

**Log Example**:
```
[13:30:00] ERROR-LIB-001-Instrument library not found: instruments_lib.json
```

---

### LIB-002: Library Corrupt
**Description**: Instrument library file is corrupted  
**Common Cause**:
- Interrupted update
- Manual edit error
- Disk corruption
- Incomplete download

**Solution**:
1. Restore library from backup
2. Download fresh copy from repository
3. Validate JSON structure
4. Reinstall application

**Log Example**:
```
[13:31:00] ERROR-LIB-002-Library file corrupted: invalid JSON structure
```

---

### LIB-003: Model Not Found in Library
**Description**: Instrument model not found in library  
**Common Cause**:
- Model not yet added
- Library outdated
- Wrong model name
- Typo in model ID

**Solution**:
1. Update instrument library
2. Add model manually
3. Check model name spelling
4. Use correct model ID format

**Log Example**:
```
[13:32:00] ERROR-LIB-003-Model 'ABC-1234' not found in library
```

---

### LIB-004: Series Not Found in Library
**Description**: Instrument series not found in library  
**Common Cause**:
- Series not added yet
- Library incomplete
- Wrong series ID
- Deprecated series

**Solution**:
1. Update library to latest version
2. Add series definition
3. Verify series ID
4. Check for series rename

**Log Example**:
```
[13:33:00] ERROR-LIB-004-Series 'XYZ_Series' not found in library
```

---

### LIB-005: Invalid Library Structure
**Description**: Library file structure is invalid  
**Common Cause**:
- Wrong format version
- Missing required sections
- Incorrect hierarchy
- Schema violation

**Solution**:
1. Validate against schema
2. Update to correct structure
3. Download correct library version
4. Migrate from old format

**Log Example**:
```
[13:34:00] ERROR-LIB-005-Invalid library structure: missing 'power_supplies_series'
```

---

### LIB-006: Missing Commands in Library
**Description**: Required SCPI commands missing from library entry  
**Common Cause**:
- Incomplete instrument definition
- Library entry not finalized
- Commands not yet implemented
- Partial instrument support

**Solution**:
1. Add missing commands to library
2. Consult instrument programming manual
3. Update library from repository
4. Complete instrument definition

**Log Example**:
```
[13:35:00] ERROR-LIB-006-Missing commands for model: reset, *IDN?
```

---

### LIB-007: Incompatible Library Version
**Description**: Library version incompatible with application  
**Common Cause**:
- Library too new
- Library too old
- Breaking format changes
- Missing migration

**Solution**:
1. Update application version
2. Downgrade library if necessary
3. Use compatible library version
4. Check version requirements

**Log Example**:
```
[13:36:00] ERROR-LIB-007-Library version 3.0 incompatible with app 2.5
```

---

### LIB-008: Library Update Failed
**Description**: Failed to update instrument library  
**Common Cause**:
- Network error during download
- Write permission denied
- Disk space insufficient
- Update server unavailable

**Solution**:
1. Check internet connection
2. Verify write permissions
3. Free disk space
4. Retry update later

**Log Example**:
```
[13:37:00] ERROR-LIB-008-Library update failed: connection timeout
```

---

## SCPI - SCPI Command Errors (SCPI-XXX)

Errors specific to SCPI command operations (distinct from general VISA errors).

### SCPI-001: Command Not Supported
**Description**: SCPI command not supported by instrument  
**Common Cause**:
- Command for different model
- Optional feature not installed
- Firmware lacks support
- Deprecated command

**Solution**:
1. Check instrument manual for supported commands
2. Verify firmware version
3. Use alternative command
4. Update firmware if available

**Log Example**:
```
[13:40:00] ERROR-SCPI-001-Command 'SYST:COMM:LAN:MAC?' not supported
```

---

### SCPI-002: SCPI Syntax Error
**Description**: SCPI command syntax error  
**Common Cause**:
- Missing parameter
- Wrong parameter format
- Extra spaces or characters
- Invalid command structure

**Solution**:
1. Check command syntax in manual
2. Verify parameter format
3. Remove extra spaces
4. Use correct separator (: or space)

**Log Example**:
```
[13:41:00] ERROR-SCPI-002-Syntax error in 'VOLT:LEV 5.0V' (unit not allowed)
```

---

### SCPI-003: Invalid SCPI Response
**Description**: Instrument returned invalid response  
**Common Cause**:
- Unexpected response format
- Corrupted data transmission
- Instrument error state
- Buffer overflow

**Solution**:
1. Verify query command syntax
2. Check instrument error queue (*ESR?)
3. Clear status and retry
4. Increase timeout if needed

**Log Example**:
```
[13:42:00] ERROR-SCPI-003-Invalid response: expected float, got 'ERROR'
```

---

### SCPI-004: SCPI Parameter Error
**Description**: SCPI command parameter error  
**Common Cause**:
- Parameter out of range
- Wrong parameter type
- Invalid parameter value
- Missing required parameter

**Solution**:
1. Check parameter range in manual
2. Use correct data type
3. Verify parameter value validity
4. Include all required parameters

**Log Example**:
```
[13:43:00] ERROR-SCPI-004-Parameter error: voltage 150V exceeds max 100V
```

---

### SCPI-005: SCPI Execution Error
**Description**: Error during SCPI command execution  
**Common Cause**:
- Instrument in wrong state
- Hardware limitation
- Resource conflict
- Calibration required

**Solution**:
1. Check instrument state
2. Verify instrument conditions
3. Clear error queue and retry
4. Consult error code in manual

**Log Example**:
```
[13:44:00] ERROR-SCPI-005-Execution error: output is off
```

---

### SCPI-006: SCPI Query Interrupted
**Description**: SCPI query operation interrupted  
**Common Cause**:
- Connection lost during query
- Timeout occurred
- Instrument reset
- Abort signal received

**Solution**:
1. Verify stable connection
2. Increase timeout value
3. Check instrument didn't reset
4. Retry query operation

**Log Example**:
```
[13:45:00] ERROR-SCPI-006-Query interrupted: connection lost
```

---

### SCPI-007: SCPI Device Error
**Description**: Instrument reported device error  
**Common Cause**:
- Hardware failure
- Calibration error
- Temperature out of range
- Internal error

**Solution**:
1. Query error: SYST:ERR?
2. Check instrument display
3. Power cycle instrument
4. Contact instrument support

**Log Example**:
```
[13:46:00] ERROR-SCPI-007-Device error: overheat protection active
```

---

## DATA - Data Acquisition Errors (DATA-XXX)

Errors related to data acquisition and processing.

### DATA-001: Data Corrupt
**Description**: Acquired data is corrupted  
**Common Cause**:
- Transmission error
- Memory corruption
- Buffer overflow
- Invalid data format

**Solution**:
1. Retry data acquisition
2. Verify instrument connection
3. Check data integrity
4. Clear buffers and restart

**Log Example**:
```
[13:50:00] ERROR-DATA-001-Corrupted data detected: CRC mismatch
```

---

### DATA-002: Invalid Data Format
**Description**: Data format is invalid or unexpected  
**Common Cause**:
- Wrong data type received
- Format mismatch
- Encoding error
- Parser failure

**Solution**:
1. Verify expected data format
2. Check instrument output format setting
3. Use correct parser
4. Validate data structure

**Log Example**:
```
[13:51:00] ERROR-DATA-002-Invalid format: expected CSV, got binary
```

---

### DATA-003: Data Acquisition Failed
**Description**: Failed to acquire data from instrument  
**Common Cause**:
- Instrument not responding
- Trigger not configured
- Buffer not ready
- Acquisition timeout

**Solution**:
1. Verify instrument ready state
2. Configure trigger settings
3. Check acquisition parameters
4. Increase acquisition timeout

**Log Example**:
```
[13:52:00] ERROR-DATA-003-Acquisition failed: instrument not triggered
```

---

### DATA-004: Data Buffer Overflow
**Description**: Data buffer overflow during acquisition  
**Common Cause**:
- Acquisition rate too high
- Buffer size insufficient
- Memory full
- Processing too slow

**Solution**:
1. Reduce acquisition rate
2. Increase buffer size
3. Process data faster
4. Use streaming mode

**Log Example**:
```
[13:53:00] ERROR-DATA-004-Buffer overflow: 50000 samples lost
```

---

### DATA-005: Data Save Failed
**Description**: Failed to save acquired data  
**Common Cause**:
- Disk full
- Permission denied
- Invalid file path
- File locked

**Solution**:
1. Free disk space
2. Check write permissions
3. Verify file path validity
4. Close file if open

**Log Example**:
```
[13:54:00] ERROR-DATA-005-Cannot save data: disk full
```

---

### DATA-006: Data Load Failed
**Description**: Failed to load data file  
**Common Cause**:
- File not found
- Corrupted file
- Wrong file format
- Incompatible version

**Solution**:
1. Verify file exists
2. Check file integrity
3. Validate file format
4. Use correct file version

**Log Example**:
```
[13:55:00] ERROR-DATA-006-Cannot load data: file corrupted
```

---

### DATA-007: Data Out of Range
**Description**: Acquired data values out of expected range  
**Common Cause**:
- Sensor overload
- Calibration error
- Incorrect scaling
- Physical limit exceeded

**Solution**:
1. Check sensor range settings
2. Verify calibration
3. Adjust scaling factors
4. Reduce input signal

**Log Example**:
```
[13:56:00] ERROR-DATA-007-Data out of range: 150.5V exceeds max 100V
```

---

### DATA-008: Data Incomplete
**Description**: Acquired data set is incomplete  
**Common Cause**:
- Acquisition interrupted
- Timeout occurred
- Buffer cleared prematurely
- Connection lost

**Solution**:
1. Restart acquisition
2. Increase timeout
3. Verify stable connection
4. Check trigger settings

**Log Example**:
```
[13:57:00] ERROR-DATA-008-Incomplete data: expected 1000 samples, got 743
```

---

## PJDB - Project Database Errors (PJDB-XXX)

Errors related to PostgreSQL project database operations.

### PJDB-001: Project Database Connection Failed
**Description**: Cannot connect to PostgreSQL project database  
**Common Cause**:
- PostgreSQL server not running
- Wrong connection parameters
- Network error
- Firewall blocking

**Solution**:
1. Verify PostgreSQL service running
2. Check host, port, credentials
3. Test network connection
4. Configure firewall rules

**Log Example**:
```
[14:00:00] ERROR-PJDB-001-Connection failed to PostgreSQL at localhost:5432
```

---

### PJDB-002: Project Database Not Specified
**Description**: Project database name not specified  
**Common Cause**:
- Missing database name in config
- Project not fully initialized
- Configuration error
- Database selection missing

**Solution**:
1. Specify database name in project
2. Complete project initialization
3. Check configuration file
4. Select database from list

**Log Example**:
```
[14:01:00] ERROR-PJDB-002-Database name not specified for project
```

---

### PJDB-003: Project Database Query Error
**Description**: Error executing database query  
**Common Cause**:
- SQL syntax error
- Table doesn't exist
- Column not found
- Permission denied

**Solution**:
1. Verify SQL syntax
2. Check table exists
3. Validate column names
4. Check user permissions

**Log Example**:
```
[14:02:00] ERROR-PJDB-003-Query error: table 'measurements' does not exist
```

---

### PJDB-004: Project Database Table Not Found
**Description**: Required database table not found  
**Common Cause**:
- Database not initialized
- Table creation failed
- Wrong database selected
- Schema migration incomplete

**Solution**:
1. Initialize database schema
2. Create missing tables
3. Verify correct database
4. Run migration scripts

**Log Example**:
```
[14:03:00] ERROR-PJDB-004-Table 'efficiency_data' not found
```

---

### PJDB-005: Project Database Timeout
**Description**: Database operation timeout  
**Common Cause**:
- Query too complex
- Large data set
- Database overloaded
- Network latency

**Solution**:
1. Optimize query
2. Reduce data set size
3. Increase timeout value
4. Check database load

**Log Example**:
```
[14:04:00] ERROR-PJDB-005-Query timeout after 30 seconds
```

---

### PJDB-006: Project Database Schema Error
**Description**: Database schema error or mismatch  
**Common Cause**:
- Schema version mismatch
- Missing schema elements
- Incorrect data types
- Migration failed

**Solution**:
1. Update schema to match version
2. Run schema migration
3. Verify data types
4. Recreate database if necessary

**Log Example**:
```
[14:05:00] ERROR-PJDB-006-Schema mismatch: expected v2.0, found v1.5
```

---

### PJDB-007: Project Database Data Integrity Error
**Description**: Data integrity constraint violation  
**Common Cause**:
- Foreign key violation
- Unique constraint violation
- NULL in required field
- Invalid data type

**Solution**:
1. Fix foreign key references
2. Ensure unique values
3. Provide required fields
4. Use correct data types

**Log Example**:
```
[14:06:00] ERROR-PJDB-007-Integrity error: foreign key constraint violation
```

---

## SYS - System Errors (SYS-XXX)

System-level errors and resource issues.

### SYS-001: System Resource Unavailable
**Description**: Required system resource not available  
**Common Cause**:
- Resource locked
- Resource in use
- Resource limit reached
- System overload

**Solution**:
1. Free system resources
2. Close other applications
3. Wait and retry
4. Restart application

**Log Example**:
```
[14:10:00] ERROR-SYS-001-Resource unavailable: serial port COM3 in use
```

---

### SYS-002: Insufficient Memory
**Description**: Not enough memory available  
**Common Cause**:
- Large data set
- Memory leak
- Too many objects
- System memory low

**Solution**:
1. Close unnecessary applications
2. Reduce data set size
3. Clear cached data
4. Restart application

**Log Example**:
```
[14:11:00] ERROR-SYS-002-Insufficient memory: cannot allocate 2GB
```

---

### SYS-003: Thread Error
**Description**: Threading operation error  
**Common Cause**:
- Thread deadlock
- Race condition
- Thread crash
- Synchronization error

**Solution**:
1. Restart affected operation
2. Check thread synchronization
3. Review concurrent operations
4. Restart application

**Log Example**:
```
[14:12:00] ERROR-SYS-003-Thread error: deadlock detected
```

---

### SYS-004: System Permission Denied
**Description**: Operation requires elevated permissions  
**Common Cause**:
- Insufficient privileges
- Protected system resource
- Admin rights required
- File/folder permissions

**Solution**:
1. Run application as administrator
2. Request elevated privileges
3. Adjust file permissions
4. Check user account rights

**Log Example**:
```
[14:13:00] ERROR-SYS-004-Permission denied: admin rights required
```

---

### SYS-005: System Dependency Missing
**Description**: Required system dependency not found  
**Common Cause**:
- Library not installed
- DLL missing
- Python package missing
- System component absent

**Solution**:
1. Install required dependency
2. Use pip install for Python packages
3. Reinstall application
4. Check requirements.txt

**Log Example**:
```
[14:14:00] ERROR-SYS-005-Dependency missing: pyvisa library not found
```

---

### SYS-006: System Initialization Failed
**Description**: System component initialization failed  
**Common Cause**:
- Configuration error
- Resource not available
- Dependency failure
- Startup error

**Solution**:
1. Check logs for specific error
2. Verify configuration
3. Restart application
4. Reinstall if necessary

**Log Example**:
```
[14:15:00] ERROR-SYS-006-Initialization failed: cannot start logger
```

---

### SYS-007: Unexpected System Error
**Description**: Unexpected or unhandled system error  
**Common Cause**:
- Unhandled exception
- Unknown error condition
- Bug in code
- System instability

**Solution**:
1. Check error logs for details
2. Restart application
3. Report bug with logs
4. Contact technical support

**Log Example**:
```
[14:16:00] ERROR-SYS-007-Unexpected error: unhandled exception in module
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
| **TOOL** | 001-099 | Tool-specific errors |
| **PROJ** | 001-099 | Project file errors |
| **INST** | 001-099 | Instrument configuration errors |
| **CFG** | 001-099 | Application configuration errors |
| **LIB** | 001-099 | Instrument library errors |
| **SCPI** | 001-099 | SCPI command specific errors |
| **DATA** | 001-099 | Data acquisition/processing errors |
| **PJDB** | 001-099 | Project database errors |
| **SYS** | 001-099 | System-level errors |

---

## Version and Changelog

**Version**: 2.0  
**Date**: February 4, 2026  
**Author**: Open Lab Automation Team

### Changelog
- **v2.0** (February 4, 2026): Major expansion with 8 new error categories
  - Added **PROJ** category (8 codes): Project file management errors
  - Added **INST** category (8 codes): Instrument configuration errors
  - Added **CFG** category (7 codes): Application configuration errors
  - Added **LIB** category (8 codes): Instrument library errors
  - Added **SCPI** category (7 codes): SCPI command specific errors
  - Added **DATA** category (8 codes): Data acquisition/processing errors
  - Added **PJDB** category (7 codes): Project database errors
  - Added **SYS** category (7 codes): System-level errors
  - Total: **99 error codes** covering comprehensive error scenarios
  - All new exception classes added to errorhandler.py
  - Complete documentation for each code with solutions

- **v1.0** (January 23, 2025): First version with structured logging system
  - Added 40 initial error codes (VISA, FILE, VALID, DB, NET, UI, DL, TOOL)
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

*Document updated on: February 4, 2026*
