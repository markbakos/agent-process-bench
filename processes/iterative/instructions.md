Follow an iterative-incremental development process for the current requirement.

1. Inspect the current requirement and the relevant existing code, tests, and documentation.

2. Identify a small, coherent increment of the requirement that can be implemented and verified independently.

3. Implement that increment.

4. Immediately run the relevant visible tests or other appropriate checks for the increment.

5. Review the result.
Fix problems discovered by verification and reassess the repository before choosing the next increment.

6. Repeat the implement-test-review cycle with additional small increments until the complete current requirement is implemented.

Do not batch the entire requirement into one large implementation phase when it can reasonably be divided into smaller working increments.

Test-first development is not required. Tests may be written or updated when useful, but production code does not need to be preceded by a failing test.

After all increments are complete, run the broader relevant visible test suite and perform any necessary cleanup or refactoring while preserving correct behavior.