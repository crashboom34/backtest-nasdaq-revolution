---
name: implement
description: "Implement a piece of work whose spec or tickets are already agreed — turn an already-understood/specified task into working code with /tdd at pre-agreed seams, then /code-review. Use for requests like 'implement this ticket' / 'build this already-agreed feature', once the design questions are settled, not while they're still open. Not for: producing the spec itself (to-spec), designing a new module's interface (codebase-design), or refactoring existing architecture (improve-codebase-architecture)."
disable-model-invocation: false
---

Implement the work described by the user in the spec or tickets.

Use /tdd where possible, at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite once at the end.

Once done, use /code-review to review the work.

Commit your work to the current branch.
