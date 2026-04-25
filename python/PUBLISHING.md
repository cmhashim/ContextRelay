# Publishing ContextRelay to PyPI

This document describes the steps to publish the `context-relay` package to PyPI.

## Prerequisites

1. PyPI account with appropriate permissions
2. Python 3.9+ installed
3. `build` and `twine` packages installed

## One-Time Setup

Install the required build tools:

```bash
pip install build twine
```

## Publish Steps

### 1. Update Version

Edit `pyproject.toml` and update the version number:

```toml
[project]
version = "0.2.0"  # Update this
```

### 2. Build the Package

From the `python/` directory (where `pyproject.toml` is located):

```bash
cd /home/hash/Projects/contextrelay/python
python -m build
```

This creates a `dist/` directory with:
- `context-relay-<version>.tar.gz` (source distribution)
- `context-relay-<version>-py3-none-any.whl` (built distribution)

### 3. Upload to PyPI

Set your PyPI credentials as environment variables:

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-XXXXXXXXXXXX
```

Alternatively, create a `.pypirc` file in your home directory:

```ini
[pypi]
username = __token__
password = pypi-XXXXXXXXXXXX
```

Then upload:

```bash
twine upload dist/*
```

### 4. Verify the Upload

Check PyPI to confirm the package is available:

```bash
pip install context-relay==<version>
```

Or visit: https://pypi.org/project/contextrelay/

## Package Structure

The package includes only the `contextrelay` directory (not tests or examples):

```
contextrelay/
├── __init__.py
├── agent_bridge.py
├── bridge_cli.py
├── client.py
├── mcp.py
├── py.typed          # PEP 561 type checking marker
└── integrations/
    ├── __init__.py
    ├── langchain.py
    ├── crewai.py
    └── autogen.py
```

## Type Checking

The package includes a `py.typed` marker file, indicating it supports PEP 561 type checking. Users can use:

```python
from contextrelay import ContextRelay  # Type hints available
```

## Optional Dependencies

The package defines optional dependency groups:

- `langchain`: `pip install context-relay[langchain]`
- `crewai`: `pip install context-relay[crewai]`
- `autogen`: `pip install context-relay[autogen]`

All integrations use `TYPE_CHECKING` guards to avoid hard dependencies.

## Notes

- The package name on PyPI is `context-relay` (not `contextrelay-mcp`)
- The MCP server entry point remains `contextrelay-mcp` for backward compatibility
- The package requires Python 3.9+ (as specified in `requires-python`)
- The license is MIT (as specified in `license`)
