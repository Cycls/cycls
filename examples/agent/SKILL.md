---
name: code-review
description: Review code for bugs, security issues, and best practices. Use when asked to review or audit code.
allowed-tools: read, grep, glob
---

# Code Review

When reviewing code, follow this process:

## 1. Understand the Context
- Read the file(s) to be reviewed
- Understand the purpose and functionality

## 2. Check for Issues
- **Bugs**: Logic errors, off-by-one errors, null pointer issues
- **Security**: SQL injection, XSS, command injection, hardcoded secrets
- **Performance**: N+1 queries, unnecessary loops, memory leaks
- **Style**: Naming conventions, code organization, documentation

## 3. Provide Feedback
- Be specific about line numbers
- Explain why something is an issue
- Suggest fixes when possible
- Prioritize critical issues first

## Output Format
```
## Summary
[Brief overview]

## Critical Issues
- [file:line] Issue description

## Suggestions
- [file:line] Improvement suggestion

## Positive Notes
- What's done well
```
