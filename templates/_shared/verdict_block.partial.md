---
version: "1.0.0"
---

## Verdict — the machine-read part of your review

Everything above this point is for a human. This block is for a parser. It is
read **literally**: the severity is the word you write on the `VERDICT:` line and
nothing else. No keyword anywhere else in your review raises or lowers it.

Your response must END with this block, in exactly this shape, with no prose
after it:

```
## Verdict
VERDICT: PASS | WARN | BLOCK
BLOCKING:
- <one finding per line> (invariant: <id> | spec: <section> | scope: <issue section>)
WARNINGS:
- <one finding per line>
```

### Rules the parser enforces

- **The `VERDICT:` line is required**, and carries exactly one of `PASS`, `WARN`,
  `BLOCK`. Omit it and the review is a parse failure. A parse failure is handled
  as a failed review — never as a PASS, so a reviewer cannot pass a change by
  going silent.
- **Leaving the literal `PASS | WARN | BLOCK` in place is a parse failure**, not
  a PASS. Choose one word.
- **`BLOCK` is legal only when at least one `BLOCKING:` line carries a
  citation.** A citation is one of:
  - `(invariant: <id>)` — an invariant id declared in this project's context.
    The parser holds the declared list and rejects an id that is not in it, so
    do not invent one; cite the id verbatim or use another citation form.
  - `(spec: <section>)` — a named section of the specification the change claims
    to implement.
  - `(scope: <section>)` — a named section of the dispatched issue body, e.g.
    `OUT OF SCOPE`, `FILES TO MODIFY`, `ACCEPTANCE CRITERIA`.

  A `BLOCK` with no citable finding is a parse failure. This is deliberate: it
  keeps BLOCK on things the project has written down, and off taste. If a finding
  is real but you cannot cite it, it is a `WARNINGS:` line.
- **`WARN` requires at least one `WARNINGS:` line.**
- **`PASS` requires both lists empty.** Write the `BLOCKING:` and `WARNINGS:`
  labels with no bullets under them, or leave them out entirely. Do not write
  "none" as a bullet — that parses as a finding.

### Worked examples

A block, cited:

```
## Verdict
VERDICT: BLOCK
BLOCKING:
- worker.py:149 writes the verdict before the store commit is checked; a store
  error drops the review silently (invariant: gate_fails_closed)
WARNINGS:
- the new helper has no docstring
```

A pass:

```
## Verdict
VERDICT: PASS
BLOCKING:
WARNINGS:
```
