<!-- Use this file to provide workspace-specific custom instructions to Copilot. For more details, visit https://code.visualstudio.com/docs/copilot/copilot-customization#_use-a-githubcopilot-instructions.md-file -->
# Copilot Instructions - PyQt6 Project

This document provides guidelines for the development and maintenance of this software based on Python and PyQt6. Follow these instructions to ensure consistency, maintainability, and a clear separation of concerns within the code.

## Project Structure

The project is organized according to the following file and directory structure:

```
/
|-- main.py                 # Main entry point of the application
|-- ui/
|   |-- main_window.py        # Code for the main window
|   |-- dialog_box_1.py       # Code for a specific dialog box
|   |-- widget_custom.py      # Code for a custom widget
|   `-- ...                   # Other files for windows and dialogs
|-- core/
|   |-- tools.py              # Generic and reusable utility functions
|   |-- errorhandler.py       # Centralized error handling
|   `-- validator.py          # Functions for data validation
|-- assets/
|   |-- icons/                # Application icons
|   `-- styles/               # Stylesheets (QSS)
`-- tests/
    |-- test_validator.py     # Tests for validation functions
    `-- ...                   # Other test files
```

## Component Description

### 1. `main.py`

*   **Purpose:** It is the application's starting point.
*   **Content:**
    *   Initialization of `QApplication`.
    *   Creation and display of the main window instance (`MainWindow` from the `ui/main_window.py` file).
    *   Starting the application's event loop.
*   **Do not modify for:** Adding business logic or UI. It should remain as simple as possible.

### 2. `ui/` Directory

*   **Purpose:** Contains all code related to the user interface.
*   **Rules:**
    *   **One file per window/dialog:** Each window (`QMainWindow`, `QWidget`) or dialog box (`QDialog`) must reside in its own Python file. For example, `user_settings_dialog.py`.
    *   **No business logic:** Files in this directory should only contain the code to create, layout, and manage widget events. Complex logic (e.g., calculations, database access) must be delegated to external functions.
    *   **Signal connections:** Signals (e.g., `button.clicked`) should be connected to methods of the same class or to functions imported from other modules (like `tools.py` or `validator.py`).

### 3. `core/tools.py` Module

*   **Purpose:** To centralize utility functions that are used in multiple parts of the application.
*   **Content:**
    *   Functions for file manipulation (e.g., `read_json`, `save_csv`).
    *   Functions for formatting dates or strings.
    *   Any other function that does not specifically fall into validation or error handling but is reusable.
*   **Rules:** Functions must be generic and not depend on the state of a specific window.

### 4. `core/errorhandler.py` Module

*   **Purpose:** To provide a single mechanism for handling and displaying errors.
*   **Content:**
    *   A main function (e.g., `handle_error(exception, message)`) that receives an exception and a descriptive message.
    *   This function can log the error to a file and/or show a `QMessageBox` to the user with a clear message.
    *   Custom exception classes (e.g., `ValidationError`, `FileAccessError`).
*   **How to use it:** Instead of a `try...except` block with a duplicated `QMessageBox` everywhere, call `errorhandler.handle_error()`.

### Standardized Error Codes System
The application implements a comprehensive error code system with format [RESOURCE-XXX]:

*   **Format:** `[RESOURCE-XXX]`
    *   **RESOURCE:** A 3-4 letter abbreviation that identifies the resource or component that generated the error (e.g., `FILE`, `DB`, `NET`, `VALID`).
    *   **XXX:** A three-digit progressive number that uniquely identifies the error within that resource.

*   **Examples:**
    *   `[FILE-001]`: Could not find the configuration file.
    *   `[VALID-005]`: The email address format is invalid.
    *   `[DB-010]`: Database connection error.

*   **Implementation:**
    *   Errors are defined in a dictionary or enum within `core/errorhandler.py`.
    *   The `handle_error` function will accept an error code as a parameter.
    *   The message shown to the user will include both the code and a friendly description, allowing for more efficient technical support. Example: `"An error occurred. Please contact support with the following code: [FILE-001]"`.
    *   Error logs must record the code, the full message, and the stack trace for detailed analysis.

### 5. `core/validator.py` Module

*   **Purpose:** To contain all functions for input data validation.
*   **Content:**
    *   Specific functions to validate data formats, types, and ranges. Examples:
        *   `is_valid_email(email)`
        *   `is_numeric(value)`
        *   `is_date_in_range(date, start, end)`
*   **Rules:**
    *   Each function should do one thing and do it well.
    *   Functions should return `True` or `False`, or raise a specific exception (e.g., `ValidationError` from `errorhandler.py`) on failure.

## Example Workflow

**Scenario:** Validate an email field in a dialog box and save the data.

1.  **`ui/my_dialog.py`:**
    *   The user presses the "Save" button.
    *   The method connected to the `clicked` signal retrieves the text from the email input.
    *   It calls `validator.is_valid_email(email_text)`.
    *   **If validation fails:**
        *   The validator raises a `ValidationError`.
        *   A `try...except` block catches the exception and calls `errorhandler.handle_error(e, "The entered email is not valid.")`.
    *   **If validation succeeds:**
        *   It calls a function from `tools.py` to save the data, for example, `tools.save_user_data(...)`.
        *   If saving fails (e.g., `FileNotFoundError`), the `try...except` block catches the error and passes it to `errorhandler.handle_error()`.
        *   If everything goes well, the dialog is closed.
