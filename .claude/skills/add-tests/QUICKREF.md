# Quick Reference: add-tests Skill

## Usage

```bash
/add-tests                    # Generate tests for current branch diff
/add-tests "feature name"     # Or specify a feature explicitly
```

## What it does

1. **Analyzes your diff** — identifies what was changed
2. **Categorizes** — is it an endpoint? Database query? React component? Lambda job?
3. **Generates test cases** — happy path, edge cases, security/auth tests
4. **Writes test files** — creates runnable pytest/vitest code
5. **Documents gaps** — lists what can't be tested and why

## Output

- `test_<feature>.py` (Django/FastAPI) or `test_<feature>.tsx` (React)
- Test summary table (component, type, count, coverage)
- Coverage checklist

## Example flow

```
Feature: Add chat session persistence
  ├─ Creates: fastapi/tests/test_chat.py (25 tests)
  ├─ Covers: auth, org scoping, SSE streaming, session lookup
  ├─ Coverage: 87%
  └─ Gap: Bedrock API integration (mocked, not tested against real API)
```

## When to use

✅ **After implementation is complete** — you have working code  
✅ **Before security review** — tests validate what you intended to do  
✅ **For quick test generation** — FNTC templates included  
✅ **When tests are blocking a PR** — autonomous, fast  

❌ Don't use if implementation is incomplete  
❌ Don't use if you need to validate the design first  
❌ Don't use if you need deep edge case discovery (use QA Tester agent)

## vs. QA Tester Agent

| | add-tests | QA Tester |
|---|----------|-----------|
| **Finds edge cases?** | Basic | Deep ✅ |
| **Writes test files?** | Yes ✅ | No |
| **Discovers design issues?** | No | Yes ✅ |
| **Fast?** | Yes ✅ | No |
| **Security-focused?** | General | Yes ✅ |

**Use both**: QA Tester first (find what to test) → add-tests (write the tests)

## Included in FNTC checklist

The skill automatically tests for:
- ✅ Org isolation (users can't see other orgs' data)
- ✅ JWT validation (missing/invalid tokens)
- ✅ Bedrock integration (mocked boto3 calls)
- ✅ Decimal precision (no float money)
- ✅ Async patterns (SSE, SQS, Lambda timeouts)
- ✅ External API mocks (Plaid, QB, Bedrock)

## Test framework assumptions

- **Django**: pytest + TestCase
- **FastAPI**: pytest + AsyncClient
- **React**: vitest + @testing-library/react
- **Lambda**: pytest + moto/responses

All tests use project fixtures (conftest.py) and follow FNTC conventions.

## After tests are generated

```bash
# Run the tests
pytest fastapi/tests/test_chat.py -v

# Check coverage
pytest --cov=fastapi --cov-report=term-missing

# If tests fail
  1. Fix the implementation (tests likely found a bug)
  2. OR adjust the tests if they're too strict

# Before merging
/security-review     # Verify no security gaps
/code-review         # Check code quality
git commit -m "Add tests for <feature>"
```

## Tips

1. **Run tests immediately** — if they fail, either the implementation or the tests are wrong
2. **Don't skip FNTC checklist** — org scoping and auth are non-negotiable
3. **Mock external APIs** — tests should never call real Plaid/QB/Bedrock
4. **Document gaps** — if something can't be tested easily, that's useful signal
5. **Use freezegun** for time-dependent tests (forecasts, date ranges, overdue logic)
