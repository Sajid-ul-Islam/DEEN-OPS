# AI Agent Skills

This directory contains skill files that define best practices and prevent common bugs when working with this codebase.

## Available Skills

| Skill | File | When to Use |
|-------|------|-------------|
| Navigation Stability | `navigation-stability.md` | When adding sidebar buttons, chat input, or any feature that might trigger navigation changes |
| Code Quality | `code-quality.md` | Before editing any Python file, especially when adding duplicate blocks or changing indentation |
| Session State Management | `session-state-management.md` | When adding, modifying, or accessing `st.session_state` variables |

## How to Use These Skills

1. **Read the relevant skill file** before making changes to code
2. **Follow the patterns** and avoid the anti-patterns listed
3. **Validate changes** using the checklist provided in each skill
4. **Test thoroughly** to ensure the fix works and doesn't break existing functionality

## Contributing New Skills

If you identify a recurring bug pattern, create a new skill file following this template:

```markdown
# Skill Name

## Overview
Brief description of the problem this skill prevents

## Problem
Detailed description of the bug symptoms

## Root Causes
List of common causes

## Prevention Guidelines
Detailed guidance with code examples

## Anti-Patterns to Avoid
Examples of what NOT to do

## Reference
Link to related files or documentation
```

## Maintaining Skills

- Update skills when new patterns emerge
- Remove outdated skills when they're no longer relevant
- Add links to related skills when they overlap
- Keep code examples consistent with current best practices
