# Tests

This directory contains the test suite for the Python GitHub Actions Runners Manager application.

## Structure

*   `unit/`: Unit tests for individual components and logic.
*   `integration/`: Integration tests that verify interactions between components.
*   `conftest.py`: Shared pytest fixtures and configuration.

## Running Tests

Ensure you have the development dependencies installed and your virtual environment activated.

### Run All Tests

To run the entire test suite:

```bash
pytest
```

### Run Specific Test Suites

**Unit Tests Only:**

```bash
pytest tests/unit
```

**Integration Tests Only:**

```bash
pytest tests/integration
```

### Coverage

To generate a test coverage report:

```bash
# Generate HTML report
pytest --cov=app --cov-report=html

# Open the report
open htmlcov/index.html
```
