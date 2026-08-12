Follow a test-driven development process for the current requirement.

For each new or changed behavior required by the current requirement:

1. Write or update visible automated tests that express the required behavior before modifying the corresponding production code.

2. Run the relevant test or tests and confirm that at least one fails for the expected reason, demonstrating that the required behavior is not yet implemented.

3. Make the smallest reasonable production-code change needed to satisfy the tested behavior.

4. Run the relevant tests again and bring them to a passing state.

5. Refactor only after the relevant tests pass. Preserve passing behavior while refactoring.

6. Repeat this test-fail-implement-pass-refactor cycle for the remaining required behaviors.

If suitable visible test infrastructure does not yet exist, establish the minimal local test infrastructure needed before implementing the corresponding production behavior.

Do not implement new required production behavior first and add its tests afterward as the normal workflow.

Before completing the requirement, run the broader relevant visible test suite to check for regressions.