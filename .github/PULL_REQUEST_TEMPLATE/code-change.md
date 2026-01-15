---
name: "Code Change"
about: "Template for code changes, bug fixes, or new features"
title: "[Type]: <short description>"
labels: ["code"]
assignees: []
---

## Change Type

- [ ] Bug Fix
- [ ] New Feature
- [ ] Enhancement
- [ ] Refactoring
- [ ] Documentation
- [ ] Performance Improvement

## Description

<!-- Provide a clear and concise description of the changes -->

## Related Issue

<!-- Link to related issue(s) -->
Closes #
Related to #

## Motivation and Context

<!-- Why is this change needed? What problem does it solve? -->

## Changes Made

### Modified Files
- `path/to/file.py` - Description of changes
- `path/to/another/file.py` - Description of changes

### New Files
- `path/to/new/file.py` - Description and purpose

## Project Structure Compliance

<!-- Confirm adherence to project guidelines from .github/copilot-instructions.md -->

- [ ] UI code is in `ui/` directory with one file per window/dialog
- [ ] Business logic is separated from UI code
- [ ] Utility functions are in `core/tools.py`
- [ ] Error handling uses `core/errorhandler.py` with standardized error codes
- [ ] Input validation uses `core/validator.py`
- [ ] Error codes follow `[RESOURCE-XXX]` format if applicable

## Testing

### Test Environment
- **OS:** <!-- e.g. Windows 11, Ubuntu 22.04 -->
- **Python Version:** <!-- e.g. 3.10.5 -->
- **PyQt6 Version:** <!-- if relevant -->

### Testing Performed
- [ ] Manual testing completed
- [ ] Unit tests added/updated
- [ ] Integration tests performed
- [ ] Tested with physical hardware (if applicable)

### Test Results
<!-- Describe the testing performed and results -->

## Screenshots

<!-- If applicable, add screenshots showing before/after or new features -->

## Code Quality Checklist

- [ ] Code follows the project structure guidelines
- [ ] Self-review completed
- [ ] Code is properly commented (especially complex logic)
- [ ] No hardcoded values (use configuration where appropriate)
- [ ] Error handling is implemented with proper error codes
- [ ] Input validation is in place
- [ ] No new linting warnings or errors
- [ ] Existing tests still pass
- [ ] Documentation updated (if needed)

## Breaking Changes

- [ ] This PR introduces breaking changes

<!-- If yes, describe the breaking changes and migration path -->

## Additional Notes

<!-- Add any other relevant information, known limitations, or future improvements -->
