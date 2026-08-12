Follow a sequential, plan-driven development process for the current requirement.

1. Analyze before implementation.
Inspect the relevant repository structure, existing behavior, visible tests, and documentation. Determine what the requirement changes, which components are affected, and what constraints must be preserved.

2. Design before implementation.
Decide on the implementation approach before modifying production code. Write or update DEVELOPMENT_PLAN.md with a concise description of:
- the requirement impact,
- the planned design or implementation changes,
- the files or components expected to change,
- the verification approach.

Complete this planning step before making production-code changes.

3. Implement according to the plan.
Make the planned production changes as a coherent implementation phase. Do not use test-first development or repeated plan-implement-test cycles as the primary workflow.

If implementation reveals that the plan is materially incorrect, update the plan before continuing with the revised approach.

4. Verify after implementation.
After the planned implementation is complete, run the relevant visible tests and other appropriate checks. Treat verification as a distinct phase.

If verification reveals defects, make the necessary corrective changes and repeat verification. Avoid unrelated redesign or functionality.

5. Complete the requirement.
Ensure the implementation satisfies the current requirement, existing behavior not superseded by it remains intact, and DEVELOPMENT_PLAN.md reflects the implemented approach.