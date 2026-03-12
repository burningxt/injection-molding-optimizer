# AGENTS.md - Coding Guidelines for Injection Molding Project

## Project Overview
注塑成型工艺参数智能推荐系统 - 基于贝叶斯优化 (Bayesian Optimization) 的注塑成型工艺参数智能推荐系统。

**Tech Stack**: Python 3.10+, PyTorch, BoTorch, FastAPI, WebSocket, pandas, Pydantic

## Build / Test / Run Commands

### Installation
```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
uv pip install -e .       # Using uv (recommended)
pip install -e .          # Using pip
```

### Running the Application
```bash
# Web interface (recommended)
uvicorn injection_molding.interfaces.web:app --host 0.0.0.0 --port 8000

# CLI mode
python -m injection_molding --config configs/parts/LS39860A-903.json --n-init 10 --n-iter 20
# Or use the entry point
im-opt --config configs/parts/LS39860A-903.json --n-init 10 --n-iter 20
```

### Testing
```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/unit/test_fitness.py

# Run specific test function
pytest tests/unit/test_fitness.py::test_calculate_gated_fitness

# Run with verbose output
pytest tests/ -v

# Run specific test category
pytest tests/unit/        # Unit tests
pytest tests/integration/ # Integration tests
pytest tests/e2e/         # End-to-end tests
```

### Code Quality
```bash
# Type checking
mypy src/

# Code formatting (if tools are installed)
black src/ tests/
isort src/ tests/

# Linting (if ruff is installed)
ruff check src/ tests/
```

## Code Style Guidelines

### Import Order
1. Standard library imports
2. Third-party imports (numpy, pandas, torch, etc.)
3. Local imports (relative imports preferred)

```python
# Standard library
import json
import re
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

# Third-party
import numpy as np
import pandas as pd
from fastapi import FastAPI, WebSocket
from pydantic import BaseModel, Field

# Local imports (relative)
from ..domain.models import PartConfig
from ..core.runner import ExperimentRunner
```

### Naming Conventions
- **Functions/Variables**: `snake_case` (e.g., `run_fitness_calculation`, `form_error`)
- **Classes**: `PascalCase` (e.g., `BayesianOptimizer`, `ExperimentRecord`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `PV_GATE`, `MAX_ITERATIONS`)
- **Private**: `_leading_underscore` for internal use
- **Abstract Base Classes**: Use `Base` prefix or `ABC` suffix

### Type Hints
- Use Python 3.10+ union syntax: `str | None` instead of `Optional[str]`
- Use `list[str]` instead of `List[str]` (from `__future__` import or Python 3.9+)
- Always type function parameters and return values
- Use Pydantic models for complex data structures

```python
def normalize_group(v: str) -> str | float:
    """把任意类似 'A 1' 标准化为 'A1'"""
    s = str(v).strip()
    m = re.search(r"([AaTt])\s*(\d{1,3})", s)
    return f"{m.group(1).upper()}{int(m.group(2))}" if m else np.nan
```

### Docstrings & Comments
- Use Chinese for docstrings and inline comments
- Use Google-style docstrings for complex functions
- Keep comments concise and meaningful

```python
def calculate_gated_fitness(row):
    """层级化（Gated）Fitness 计算
    
    Args:
        row: DataFrame row containing PV, MAE, SYM, SUI values
        
    Returns:
        float: Calculated fitness value
    """
    PV_GATE = 0.5
    # ... implementation
```

### Error Handling
- Use specific exceptions, avoid bare `except:`
- Provide meaningful error messages in Chinese
- Use `try/except` for file I/O and external calls
- Log errors with traceback for debugging

```python
try:
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)
except FileNotFoundError:
    raise RuntimeError(f"配置文件不存在: {config_path}")
except json.JSONDecodeError as e:
    raise RuntimeError(f"配置文件格式错误: {e}")
```

### Pydantic Models
- Use for all data validation and serialization
- Use `Field()` for default values and constraints
- Use `Enum` for choices/literals

```python
class AlgoSettings(BaseModel):
    """算法设置"""
    n_init: int = Field(default=20, ge=1, le=100)
    n_iter: int = Field(default=10, ge=1, le=100)
    batch_size: int = Field(default=4, ge=1, le=20)
    mode: Literal["auto", "manual"] = "manual"
```

### Project Structure
```
src/injection_molding/
├── core/           # Algorithm layer (Bayesian opt, fitness calc)
├── domain/         # Domain layer (config, models)
├── infrastructure/ # Infrastructure (persistence, utils)
├── interfaces/     # Interface layer (CLI, Web)
└── agents/         # Agent layer (reserved)
```

### Key Principles
1. **Layered Architecture**: Keep domain logic separate from interfaces
2. **Human-in-the-Loop**: Design for interactive optimization with user input
3. **Type Safety**: Use Pydantic and type hints throughout
4. **Chinese UI**: All user-facing messages should be in Chinese
5. **Checkpointing**: Support save/resume for long-running optimizations
6. **Async-First**: Web layer uses async/await for WebSocket support

### Testing Guidelines
- Place tests in `tests/unit/`, `tests/integration/`, `tests/e2e/`
- Use `pytest-asyncio` for async tests
- Mock external dependencies (file I/O, network)
- Test edge cases (empty data, invalid inputs)
- Use descriptive test function names

### File Organization
- One class per file for major components
- Group related utilities in `*_utils.py` or `utils.py`
- Keep web services in `interfaces/web/services/`
- Store configurations in `configs/parts/` as JSON
