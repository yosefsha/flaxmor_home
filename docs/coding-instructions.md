# Coding Instructions

## General

- All configuration must be production-ready standard — no placeholder values, TODO stubs, or "good enough for now" defaults. Every config entry should be deployable to production as-is.

## Python / FastAPI

### Project Structure
```
app/
  __init__.py
  main.py            # FastAPI app, route definitions
  models.py           # Pydantic request/response schemas
  <domain>.py         # Business logic classes
  <domain>_loader.py  # Data loading / parsing utilities
tests/
  __init__.py
  test_<module>.py    # Mirror app/ structure
config/
  *.json              # Runtime configuration files
```

### Code Style
- Type-annotate all function signatures including return types.
- Use `dataclass(frozen=True)` for internal value objects that don't need Pydantic validation.
- Use Pydantic `BaseModel` for API request/response schemas.
- Route handlers must be thin — delegate to business logic classes.
- Use `snake_case` for functions and variables, `PascalCase` for classes.
- One class/concern per file.

### Configuration
- Use environment variables for all runtime configuration (DB URLs, file paths, feature flags).
- Provide sensible defaults so local development works without any env vars set.
- Load configuration at module level so it's available at startup.

### Testing
- Use `pytest` as the test runner.
- Use FastAPI's `TestClient` for API/integration tests.
- Unit tests should construct dependencies inline (no shared global fixtures for business logic).
- Test both success paths and error/edge cases.
- Run a single test: `pytest tests/test_file.py::test_name`

### Dependencies
- Pin minimum versions in `requirements.txt` (e.g., `fastapi>=0.115.0`).
- For production, generate a locked `requirements.lock` with exact versions.

---

## React / TypeScript

### Project Structure
```
src/
  main.tsx            # Entry point
  App.tsx             # Root component
  types.ts            # Shared type definitions
  parser.ts           # Pure utility functions
  components/
    <Name>.tsx        # One component per file, PascalCase filename
```

### Code Style
- Functional components only — no class components.
- Define props as a standalone `interface Props` above the component.
- Use named exports for all components (exception: root `App`).
- `camelCase` for functions/variables, `PascalCase` for components/types/interfaces.
- Keep parsing and transformation logic in pure functions outside components.
- Shared types go in `types.ts`, not scattered across components.

### State & Effects
- Use `useEffect` cleanup functions for mount/unmount lifecycle work.
- Derive state from props where possible instead of duplicating into local state.

### Layout
- Use CSS Grid or Flexbox via inline styles unless a CSS framework is adopted.

### Build & Lint
- `npm run dev` — Vite dev server with HMR.
- `npm run build` — Type-check (`tsc -b`) then Vite production build.
- `npm run lint` — ESLint.
