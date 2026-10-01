# RetryLab

An idempotency fuzzer and bug zoo.

## Architecture
RetryLab tests idempotency guarantees by running scenarios concurrently and comparing the final database and mock-service state against a single clean run.

## Development
This project uses `uv` for dependency management.

```bash
uv venv
uv pip install -e ".[dev]"
```
