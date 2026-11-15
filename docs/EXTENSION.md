# Signature extension: X2, proposal experiments

**Question.** Does the way a proposal opens change whether clients reply?

**The two strategies, implemented in the Proposal Writer** (`agent/nodes/writer.py`, chosen per run with `strategy`):

| Arm | Strategy | What changes |
|---|---|---|
| A | `goal_first` (default) | The first sentence restates the client's specific goal; proof follows |
| B | `proof_first` | The first sentence is the strongest *proven* result for this job (with its evidence id); the goal follows |

Both arms go through the same claim verification, Critic and Compliance. Only the opening differs. On the
model path, the strategy is also a writer-prompt instruction (`STRATEGIES` in `writer.py`).

**Design** (`evals/runners/ab_test.py`)
- **Paired:** both arms draft and submit for the **same jobs**: the first 40 bid jobs per persona, giving 117
  usable pairs.
- **Separate simulators:** each arm runs in a fresh GigSim, which then advances 80 simulated hours.
- **Outcome:** a reply means the simulated client replied, asked for an interview or hired.
- **Tests:** McNemar's exact test on the discordant pairs, the correct test for paired binary outcomes, plus a
  two-proportion z-test for reference.
- **Rerun:** `python -m evals.runners.ab_test --n 40`, which writes `evals/results/ab_test.json`.

<!-- results:start -->
| Arm | Proposals | Replies | Reply rate | Hidden client score |
|---|---|---|---|---|
| A goal_first | 117 | 94 | 0.803 | 0.764 |
| B proof_first | 117 | 90 | 0.769 | 0.764 |

Difference (B - A): -0.034. McNemar exact p = 0.6177 (20 jobs replied only under A, 16 only under B);
two-proportion z = -0.638, p = 0.5235. **Not significant at 0.05.**
<!-- results:end -->

**Decision.** Keep `goal_first` as the default. The experiment found no evidence that leading with proof helps,
and the simulator's hidden client score is identical for both arms. That means GigSim's clients score the content
(coverage, metrics, read-check word), not the order. The reply-rate gap is within the simulator's randomness.

**Caveats.**
- These are rule-mode drafts on the stand-in GigSim.
- With 117 pairs, the test can only detect a large effect (roughly 10 or more points).
- Rerun with the model profile (`GROQ_API_KEY`), where opening style changes the whole letter, and on the official
  GigSim once it is released.

**Why X2.** GigBid already had GigSim outcome runs and per-category outcome memory. X2 turns that into a
repeatable experiment loop: change one thing in the writer, run both arms on the same jobs, and ship only what
wins with significance.
