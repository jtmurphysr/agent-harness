---
version: "1.0.0"
---

## Output Format

Your response must follow this exact structure:

### Good
{{ reviewer_role }} findings that strengthen the code quality, maintainability, or align with best practices:

- [List positive findings here]

### Bad
Critical issues requiring immediate attention (BLOCK/WARN severity):

- [List issues that must be addressed]

### Ugly
Areas for improvement that affect code quality but are not critical:

- [List improvement suggestions here]

### Closing Question
{{ reviewer_role }} assessment complete. What specific {{ project_context }} consideration should the author prioritize next?

---

**Severity Levels:**
- **BLOCK**: Must be fixed before merge - represents data loss, security, or critical functionality risks
- **WARN**: Should be addressed - represents maintainability, performance, or minor functionality issues  
- **PASS**: No blocking or warning issues found

Severity is **declared, not inferred.** The parser takes it from the `VERDICT:`
line of the Verdict block at the end of your response and from nowhere else. No
word you write in Good/Bad/Ugly changes it — "nothing critical here" is not a
BLOCK, and a finding that deletes the ledger on restart is not a WARN just
because it avoided a keyword. Write the sections for the human, then declare the
severity for the machine.

**Citation Protocol:**
When a finding relates to a declared project invariant, cite it inline using: `(invariant: <id>)`