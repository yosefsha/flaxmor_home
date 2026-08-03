# add-tests Skill vs. QA Tester Agent — Comparison

## Overview

| Aspect | **add-tests Skill** | **QA Tester Agent** |
|--------|-------------------|-------------------|
| **Purpose** | Generate & write tests for implemented features | Analyze code for bugs, security gaps, edge cases |
| **When to use** | After implementation, before merge (test creation) | During/after implementation, as needed (test finding) |
| **Output** | Runnable test files with full test code | Test case ideas, edge case analysis, coverage gaps |
| **Interaction** | Autonomous; creates files directly | Collaborative; reports findings for discussion |
| **Scope** | Test suite creation | Code review & validation |

---

## Pros & Cons

### add-tests Skill

#### Pros ✅
1. **Autonomous test creation**: Doesn't require back-and-forth. Analyzes diff, generates `test_*.py` files directly.
   - Saves time when you want complete test coverage quickly
   - Predictable output structure

2. **Project-aware templates**: Includes FNTC-specific patterns (org scoping, JWT auth, Bedrock mocking, Decimal precision).
   - Tests follow project conventions automatically
   - Reduces manual boilerplate

3. **Test framework defaults**: Knows the project uses pytest, FastAPI AsyncClient, vitest, etc.
   - No need to explain test setup each time
   - Consistent test style across the codebase

4. **Generates runnable code immediately**: You can `pytest` the tests right away.
   - Fast feedback loop
   - Can iterate on failed tests quickly

5. **Multiple test types in one pass**: Generates unit, integration, component tests all in one skill invocation.
   - Covers Django, FastAPI, React, Lambda in the same session
   - Cross-layer feature testing

#### Cons ❌
1. **Less interrogation**: Doesn't probe edge cases as deeply as QA Tester.
   - May miss subtle logical flaws
   - Tests what's obvious, not what's hidden

2. **No real code understanding**: Creates test templates; doesn't deeply analyze the business logic.
   - Could generate tests that pass but don't validate correctness
   - Won't catch "tests the wrong behavior"

3. **Skill outputs files directly**: Can't easily review before creation.
   - No chance to adjust test strategy before files are written
   - If tests are wrong, you need to edit them

4. **No security vetting**: Focuses on coverage, not security gaps.
   - Might miss Bedrock injection, SQL injection, IDOR patterns
   - Should be paired with `/security-review` before merge

5. **Limited to test writing**: Doesn't fix bugs it finds.
   - If implementation has a flaw, skill will test the flawed behavior
   - Need `/code-review` to catch bugs

---

### QA Tester Agent

#### Pros ✅
1. **Deep interrogation**: Asks "what if" questions, probes edge cases systematically.
   - Catches subtle bugs: off-by-one errors, race conditions, state inconsistencies
   - Forces you to think about scenarios you hadn't considered

2. **Real code understanding**: Reads the actual implementation, understands the logic flow.
   - Can identify "the test is correct but the code is wrong"
   - Spots logical flaws, not just missing coverage

3. **No premature output**: Ideas are discussed before test code is generated.
   - Can redirect strategy before writing
   - Collaborative — you steer the testing approach

4. **Security-aware**: Trained to hunt for IDOR, injection, auth bypass, data leaks.
   - Can find vulnerabilities while analyzing edge cases
   - Complements `/security-review`

5. **Flexible scope**: Can zero in on specific high-risk areas.
   - "Test the chat tool-calling loop for prompt injection"
   - "Verify org isolation in the forecast endpoint"

#### Cons ❌
1. **Doesn't write test files**: Only identifies what to test.
   - You have to write the actual test code
   - Slower if you want complete, runnable tests

2. **Manual transcription required**: You translate its findings into pytest/vitest code.
   - Opportunity for error
   - Slower time-to-first-test

3. **Less project-specific defaults**: Doesn't know your test framework setup by default.
   - Might suggest test patterns that don't match your repo's style
   - Requires more detailed explanation of your testing setup

4. **Variable depth**: Quality depends on the scope you give it.
   - "Test this function" → shallow analysis
   - "Tear apart this auth logic" → thorough analysis

5. **Harder to parallelize**: Requires sequential interaction (Q&A back-and-forth).
   - Slower for large features with many components
   - Not ideal when you want tests written quickly

---

## Decision Matrix

| Scenario | Best Tool |
|----------|-----------|
| **"I finished this feature, please generate tests ASAP"** | **add-tests skill** (autonomous, fast) |
| **"I'm worried about edge cases in this logic"** | **QA Tester agent** (deep interrogation) |
| **"Found a bug — make sure tests would catch it"** | **QA Tester agent** (reverse-engineers the fix) |
| **"Complete test coverage needed for PR"** | **add-tests skill** (multi-layer, runnable) |
| **"Is this new endpoint secure?"** | **QA Tester agent** (security-focused) + **/security-review** (automated scan) |
| **"Refactor this function — need to verify it still works"** | **QA Tester agent** (validates behavior preservation) |
| **"New integration with Bedrock — what scenarios matter?"** | **QA Tester agent** (expert elicitation) |
| **"Add tests to this Django model"** | **add-tests skill** (template-driven) |

---

## Recommended Workflow

### Standard feature implementation → merge

```
1. [Implement feature on feature branch]
2. /add-tests                              ← Generate test suite
3. pytest <test files>                     ← Run tests locally
4. /security-review                        ← Security scan
5. [Address any security issues]
6. /code-review                            ← Code quality check
7. [Fix any review items]
8. Create PR + merge
```

### Complex or high-risk feature

```
1. [Implement feature]
2. /grill-me <feature>                     ← Challenge the design
3. [Refine implementation based on findings]
4. /qa-tester [invoke agent]               ← Deep edge case analysis
5. [Update code based on QA findings]
6. /add-tests                              ← Generate tests
7. pytest <test files>
8. /security-review
9. [Address findings]
10. /code-review
11. Create PR
```

### Security-critical feature (auth, data access, Bedrock)

```
1. [Implement feature]
2. /security-review --comment              ← Check before test writing
3. [Fix security issues immediately]
4. /qa-tester                              ← Security-focused edge cases
5. [Refine based on IDOR/injection risks]
6. /add-tests                              ← Generate tests
7. pytest
8. /code-review
9. Merge
```

---

## Integration Strategy

The two tools are **complementary**, not competing:

1. **QA Tester** is for thinking about *what* to test (discovery phase)
2. **add-tests** is for writing the tests (execution phase)

### When to use both in the same session

**Scenario**: You built a complex financial chat feature with tool-calling.

```
Step 1: Invoke QA Tester
  → Asks: "What if the model asks for data it shouldn't have?"
  → Asks: "What if tool-calling loops forever?"
  → Asks: "What if Bedrock is down? Does SSE degrade gracefully?"
  → Suggests 12 test scenarios

Step 2: Update implementation based on QA findings
  → Add retry logic, timeout guard, etc.

Step 3: Invoke add-tests skill
  → Generates test_chat.py with 20 test cases
  → Includes org isolation tests, Bedrock mock tests, timeout tests
  → (Many of these were suggested by QA Tester)

Step 4: pytest
  → Runs all 20 tests
  → One fails: "tool loop timeout" — implementation gap
  
Step 5: Fix the implementation
  → Add max-iterations guard

Step 6: Re-run tests
  → All pass
```

---

## Which to choose for each task

### Task: "Build a new API endpoint for fetching customer invoices"

**Use add-tests** because:
- Straightforward CRUD endpoint
- Test patterns are well-established (auth, filtering, org scoping)
- Skill templates match exactly what you need
- Fast iteration: generate tests → run → refine

**Don't need QA Tester** because:
- No complex state machine or algorithm
- Edge cases are obvious (invalid ID, missing auth, wrong org)
- Standard REST semantics

---

### Task: "Implement tool-calling loop for Bedrock chat"

**Use both**:

1. **QA Tester first**:
   - "Can the model request its own org_id?" (injection)
   - "Does the loop terminate if Bedrock returns malformed JSON?"
   - "What if a tool takes 30s — do we timeout gracefully?"
   - "Can two concurrent chats interfere with each other?"

2. **add-tests second**:
   - Generates test boilerplate (mocking Bedrock, SSE streaming, org fixtures)
   - Implements the edge cases QA Tester identified
   - Includes FNTC-specific checklist (Bedrock, org scoping, etc.)

---

### Task: "Add Plaid webhook for real-time transaction sync"

**Use QA Tester** because:
- **Security-critical** (webhook signature verification)
- **Concurrency risk** (multiple webhooks for same org)
- **State consistency** (transaction dedup, partial sync failures)
- **External integration** (what if Plaid sends malformed data?)
- QA Tester will interrogate all these; add-tests can't discover them alone

**Then use add-tests** to write the discovered test cases.

---

## When NOT to use each

### Don't use add-tests if...
- Implementation is incomplete or buggy (test first with QA Tester)
- Feature requires significant refactoring (generate tests after refactor)
- You need to validate the design (use `/grill-me` or `/grill-with-docs` first)
- Tests are truly custom (e.g., performance benchmarks, load tests)

### Don't use QA Tester if...
- You need tests written fast (skill is quicker)
- Edge cases are already obvious and documented
- You're on a tight deadline and tests just need "reasonable coverage"
- Feature is simple (CRUD endpoint, utility function)

---

## Summary

| Use Case | Tool | Why |
|----------|------|-----|
| **Fast test generation** | add-tests | Autonomous, template-driven |
| **Find edge cases** | QA Tester | Deep interrogation |
| **Security vetting** | QA Tester | Expert analysis |
| **Complex logic** | Both (QA first, then add-tests) | Discover → implement → test |
| **Standard CRUD** | add-tests | Overkill to use QA |
| **Refactoring confidence** | QA Tester | Behavior preservation validation |
| **Time-critical merge** | add-tests | Quickest path to runnable tests |

**Best practice**: Use **add-tests skill** for most features, invoke **QA Tester agent** when risk is high or logic is complex.
