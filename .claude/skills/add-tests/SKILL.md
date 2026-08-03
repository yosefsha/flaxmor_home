---
name: add-tests
description: Generate comprehensive test suite for implemented features. Analyzes code diff, identifies test cases (happy path, edge cases, security), creates test files, and documents coverage gaps. Use after implementing a feature to add tests before merge.
argument-hint: "feature name or description (optional)"
context: fork
---

# Add Tests for Implemented Feature

## What we're testing

The diff on the current branch: !`git diff main --name-only`

Full diff context: !`git diff main`

If a specific feature was mentioned: $ARGUMENTS

---

## Step 1 — Analyze the implementation

### 1A — Identify what was changed
- **Files modified**: Which files contain new/modified code?
- **New functions/classes**: What are the public entry points?
- **Dependencies**: What external APIs, libraries, or internal modules does this code touch?
- **Data flow**: Where does input come from, where does output go?

### 1B — Categorize the feature type
- **API endpoint** (Django REST / FastAPI)
- **Database query / model** (Django ORM / SQL)
- **Business logic** (service, utility, transformer)
- **Frontend component** (React, hooks, state management)
- **Async job** (Lambda, Celery, SQS consumer)
- **Integration** (Plaid, QB, Bedrock, external service)
- **Utility / helper**

---

## Step 2 — Design test cases

For each category, generate test cases covering:

### Common to all
- **Happy path**: normal, expected usage
- **Invalid input**: null, empty string, wrong type, negative numbers
- **Boundary values**: zero, max int, empty list, single-item list
- **Error handling**: what exceptions should be raised? Are they caught gracefully?

### API endpoints (Django / FastAPI)
- **Auth**: missing Bearer token, invalid token, expired token, wrong user/org
- **Input validation**: missing required field, extra fields, schema mismatch
- **HTTP methods**: GET/POST/PUT/DELETE — correct status codes (200, 201, 400, 401, 403, 404)
- **Org scoping** (FNTC-critical): verify user can't see other orgs' data, can't modify other orgs' records
- **Pagination / filtering**: applies filters correctly, respects limits
- **Side effects**: creates/updates/deletes correct record, triggers expected notifications/logs

### Database queries (Django ORM / asyncpg)
- **Org scoping**: query includes `WHERE org_account_id = ...`
- **Unique constraints**: duplicate inserts fail gracefully
- **Foreign keys**: orphaned references, cascading deletes
- **Transactions**: partial failure doesn't corrupt state
- **Null handling**: nullable vs non-nullable fields
- **Soft deletes** (if applicable): archived vs deleted records

### Business logic (service, transformer)
- **Pure functions**: same input → same output, no state mutations
- **State changes**: idempotent, correct order of operations
- **Edge cases**: empty collection, single item, large datasets
- **Numeric precision**: Decimal fields (money), rounding behavior
- **Date/time**: timezone handling, leap years, daylight savings

### Frontend components (React)
- **Rendering**: component mounts, displays correct data
- **User interactions**: click, type, scroll → correct state changes and callbacks
- **Props validation**: required vs optional, type checking
- **Hook side effects**: useEffect dependencies, cleanup
- **Error states**: handles missing/failed API responses

### Async jobs (Lambda / SQS)
- **Message parsing**: valid SQS body, malformed JSON, missing fields
- **Idempotency**: processing same job twice doesn't duplicate results
- **Timeout**: job completes within Lambda 15min timeout
- **Dead letter queue**: failed jobs land in DLQ with metadata
- **Owner verification**: job belongs to correct org (IDOR check)

### Integrations (Plaid, QB, Bedrock)
- **API success**: happy path returns expected data
- **API errors**: rate limit, auth failure, service down → graceful degradation
- **Webhook security**: verify request signature (if webhook)
- **Data transformation**: external data maps correctly to internal schema
- **Partial success**: one product fails but others succeed (resilience)

---

## Step 3 — Choose test framework & location

### Django / Python backend tests
- **Framework**: `pytest` (modern) or Django's `TestCase` (legacy)
- **Location**: `server/apps/fintech/fntc_main_app/tests/test_<feature>.py`
- **Fixtures**: `conftest.py` (shared setup, mocked API clients)
- **Mocking**: `responses` (HTTP), `moto` (AWS), `freezegun` (time)

### FastAPI tests
- **Framework**: `pytest` + `httpx.AsyncClient`
- **Location**: `fastapi/tests/test_<feature>.py`
- **Setup**: `conftest.py` (asyncpg test DB, JWT tokens, org/user fixtures)

### Frontend tests (React)
- **Framework**: `vitest` (or `jest`) + `@testing-library/react`
- **Location**: `frontend/src/__tests__/<feature>.test.tsx`
- **Mocking**: `vi.mock()` (APIs, modules), `userEvent` (interactions)

### Lambda tests
- **Framework**: `pytest`
- **Location**: `lambda/forecast_processor/tests/test_<feature>.py`
- **Setup**: local DB or container, mock SQS messages, mock boto3 calls

---

## Step 4 — Write tests

### Template: Django REST endpoint test
```python
import pytest
from django.test import TestCase
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model

@pytest.mark.django_db
class TestMyEndpoint(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            username='testuser', password='testpass'
        )
        self.org = OrgAccount.objects.create(name='Test Org')
        self.user_org = UserOrgProfile.objects.create(
            user=self.user, org_account=self.org, is_active=True
        )
        
    def test_happy_path(self):
        """Valid request returns 200 with correct data."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/endpoint/')
        assert response.status_code == 200
        
    def test_missing_auth(self):
        """Missing Bearer token returns 401."""
        response = self.client.get('/api/endpoint/')
        assert response.status_code == 401
        
    def test_org_isolation(self):
        """User from org A cannot see org B's data."""
        org_b = OrgAccount.objects.create(name='Org B')
        # Create data in org B
        # Try to access as user from org A
        # Verify 404 or empty response
```

### Template: FastAPI test
```python
import pytest
from httpx import AsyncClient
from fastapi.testclient import TestClient

@pytest.mark.asyncio
async def test_chat_endpoint(auth_client: AsyncClient, test_org):
    """Chat endpoint with valid auth streams response."""
    response = await auth_client.post(
        "/stream/chat/",
        json={"message": "What is my balance?"}
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")

@pytest.mark.asyncio
async def test_chat_missing_org(auth_client: AsyncClient):
    """Chat without active org returns 403."""
    # Deactivate user's org
    response = await auth_client.post(
        "/stream/chat/",
        json={"message": "test"}
    )
    assert response.status_code == 403
```

### Template: React component test
```typescript
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MyComponent } from './MyComponent';

describe('MyComponent', () => {
  it('renders button and calls onClick on click', async () => {
    const handleClick = vi.fn();
    render(<MyComponent onClick={handleClick} />);
    
    const button = screen.getByRole('button', { name: /click me/i });
    await userEvent.click(button);
    
    expect(handleClick).toHaveBeenCalledOnce();
  });

  it('displays loading state while fetching', async () => {
    render(<MyComponent />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
    
    await waitFor(() => {
      expect(screen.queryByText(/loading/i)).not.toBeInTheDocument();
    });
  });
});
```

---

## Step 5 — Run & verify coverage

```bash
# Django tests
pytest server/apps/fintech/fntc_main_app/tests/test_<feature>.py -v

# FastAPI tests
pytest fastapi/tests/test_<feature>.py -v

# Frontend tests
npm run test -- src/__tests__/<feature>.test.tsx

# Coverage
pytest --cov=server/apps/fintech/fntc_main_app --cov=fastapi --cov-report=term-missing
```

**Coverage target**: 80%+ for new code. If a test is hard to write, that's often a sign the code is hard to test — refactor first.

---

## Step 6 — Document coverage gaps

If full coverage is not practical (e.g., integration with Plaid, third-party service), document:
- What scenarios are **not** tested and why
- How would you test them if resources allowed (contract testing, staging env, etc.)
- Is there a lower-risk path to partial coverage?

Example:
```
### Gaps
- **Plaid API integration** (not tested)
  - Why: requires Plaid sandbox account
  - How to test: responses library to mock Plaid HTTP, or use Plaid's own test env
  - Current: integration tested manually in staging
```

---

## Output format

### Summary table
```
| Component | Test Type | Count | Coverage |
|-----------|-----------|-------|----------|
| models.py | unit | 12 | 95% |
| views.py | integration | 8 | 80% |
| hooks/ | component | 6 | 75% |
| Total | — | 26 | 83% |
```

### Coverage report
```
✅ Happy paths — 5 tests
✅ Auth & scoping — 4 tests (org isolation, invalid token, etc.)
⚠️ Error handling — 2 tests (missing 1 for timeout scenario)
⚠️ Edge cases — 1 test (missing numeric precision, empty list)
```

### Test files created
```
- server/apps/fintech/fntc_main_app/tests/test_financial_chat.py (45 lines)
- fastapi/tests/test_chat.py (60 lines)
- frontend/src/__tests__/ChatPage.test.tsx (35 lines)
```

---

## FNTC-specific testing checklist

Before closing: verify your tests cover these FNTC patterns:

- [ ] **Org isolation**: tests verify users can't access other orgs' data
- [ ] **JWT validation**: tests check missing/invalid/expired tokens
- [ ] **Bedrock integration** (if applicable): mock boto3 calls, verify tool-calling loop
- [ ] **Database secrets**: no hardcoded passwords in test DB connection strings
- [ ] **Async patterns**: SSE endpoints, SQS consumers, Lambda handlers have proper timeout tests
- [ ] **Financial data precision**: Decimal fields tested, not floats
- [ ] **Time-based logic**: freezegun used for date-dependent tests
- [ ] **External API mocks**: Plaid, QB, Bedrock calls use responses/moto, not real API
