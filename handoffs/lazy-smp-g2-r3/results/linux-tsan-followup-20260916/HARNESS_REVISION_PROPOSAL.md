# Proposed r4 portable harness (NOT IMPLEMENTED)

Reason: the unchanged r3 C11-thread probe and a publication-free C11 smoke both
abort in sanitizer function-entry handling with null thread state. pthread
negative controls are correctly instrumented on the same runners.

Create a separate versioned r4 handoff if this proposal is accepted:

1. Preserve r3, PR #18 and this evidence directory byte-for-byte.
2. Reuse the SAME production type/function extraction and source hashes.
3. Replace only the portable harness's thread launch/join/yield adapters with
   pthread equivalents, including correct void* entry/return handling and checks
   of pthread create/join results. Do not add a second production implementation.
4. Retain eight writers, four readers, 100000 iterations each, all payload
   consistency assertions, start synchronization, mismatch/paused-writer/wrap
   checks, and the requirement for at least one accepted read. Preserve all atomic
   types and memory orders. Any further harness change requires separate review.
5. Add an independent pthread smoke and deliberately racy pthread negative
   control to validate the threading path actually used by the revised harness.
6. Generate a new manifest/probe SHA and a verify script that still fails closed
   on non-verbatim production extraction. Review the r3-to-r4 harness diff.
7. Run the specified Clang/TSan command and five fresh processes under the same
   timeout, with hashes and raw logs; never transfer r3 results to r4.

No r4 probe was generated or executed in this task. This proposal does not waive
any assertion or detector report and does not certify Windows lifecycle or G2-G6.
