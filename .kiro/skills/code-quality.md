# Code Quality & Syntax Validation Skill

## Overview

This skill helps prevent syntax errors, code duplication, and indentation issues that can break Streamlit applications.

## Common Syntax Issues

### 1. Duplicate Code Blocks

**Problem**: Multiple `else:` or `elif:` blocks at the same indentation level
```python
# BAD
if condition1:
    do_a()
else:
    do_b()
else:  # SyntaxError: invalid syntax
    do_c()
```

**Solution**: Use `elif` for additional conditions
```python
# GOOD
if condition1:
    do_a()
elif condition2:
    do_b()
else:
    do_c()
```

### 2. Indentation Errors

**Problem**: Code blocks with inconsistent indentation
```python
# BAD
if condition:
    do_something()
  else:  # IndentationError
    do_other()
```

**Solution**: Use consistent 4-space indentation
```python
# GOOD
if condition:
    do_something()
else:
    do_other()
```

### 3. Undefined Variables in Code Blocks

**Problem**: Code references variables not defined in that scope
```python
# BAD
if condition:
    m_df = get_data()
else:
    # m_df not defined here!
    process(m_df)
```

**Solution**: Ensure all variables are defined in all code paths
```python
# GOOD
if condition:
    m_df = get_data()
    process(m_df)
else:
    m_df = get_default_data()
    process(m_df)
```

## Prevention Guidelines

### 1. Always Validate Python Syntax

After any file edit, run syntax validation:

```bash
# Windows PowerShell
python -m py_compile "path\to\file.py"
```

Or use the streamlit app directly:
```bash
streamlit run app.py
```

### 2. Check for Duplicate Blocks

Before editing, verify no duplicate blocks exist:
```bash
# Search for duplicate else blocks
findstr /N "^\s*else:" "file.py"
```

### 3. Verify Variable Scope

Before using a variable, ensure it's defined in all code paths:
- Check all `if`/`elif`/`else` branches
- Check all functions that might be called
- Check loop scopes

### 4. Use Consistent Indentation

- Always use 4 spaces per indentation level
- Never mix tabs and spaces
- Use an editor that shows whitespace characters

### 5. Test Critical Code Paths

After fixing syntax errors, test:
1. Normal execution path
2. Error handling path
3. Edge cases
4. Sidebar button interactions

## Case Study: Dashboard Output Corruption

### Problem
File `dashboard_output.py` had corrupted structure with:
1. Duplicate `else:` blocks at lines 295 and 336
2. Code referencing undefined variables (`m_df`, `status_col_m`, `c_df`) in wrong branches
3. Inconsistent indentation (13 spaces vs 12)

### Root Cause
- Multiple developers edited the file without proper code review
- No syntax validation run after changes
- No duplicate block check performed

### Solution
1. Removed lines 295-338 (duplicate broken else block)
2. Verified single `else:` block remains for ingestion mode
3. Fixed indentation inconsistencies
4. Added syntax validation check

### Verification
```bash
python -m py_compile "h:\Repo\DEEN-OPS\src\pages\dashboard_output.py"
# Syntax OK
```

## Case Study: Data Pilot Duplicate Initialization

### Problem
`agent_messages` initialized twice in `data_pilot.py`:
- Line 331-332: At start of `render_ai_pilot_page()`
- Line 353-354: Later in the function

### Impact
- Second initialization overwrites first, losing chat history
- Sidebar reruns could trigger the second initialization
- Chat messages would disappear unexpectedly

### Solution
1. Kept only the first initialization (at page start)
2. Removed the second initialization block
3. Ensured chat state is preserved across reruns

## Syntax Validation Checklist

After editing any Python file:

```bash
# 1. Syntax check
python -m py_compile "path/to/file.py"

# 2. Check for duplicate else blocks
findstr /N "^\s*else:" "path/to/file.py"

# 3. Check indentation consistency (look for mixed spaces/tabs)
# Check if any line has 0, 4, 8, 12, 16, 20, 24, 28, 32 spaces for indentation

# 4. Verify no undefined variables in code blocks
# Read the file and check all variables are defined before use

# 5. Test the specific functionality
# Run streamlit and test the affected features
```

## Anti-Patterns to Avoid

❌ **DON'T**: Add code without checking for duplicates
```python
# BAD - might create duplicate else block
if m_df is not None:
    process()
else:
    fallback()
# ... more code ...
else:  # DUPLICATE!
    another_fallback()
```

❌ **DON'T**: Edit files without syntax validation
```python
# BAD - no validation after edit
# Edit file
# No python -m py_compile run
# Bug enters codebase
```

❌ **DON'T**: Mix tabs and spaces for indentation
```python
# BAD - inconsistent indentation
if condition:
    tab_here  # Using tab
    space_here  # Using spaces
```

✅ **DO**: Validate syntax after every edit
```bash
# GOOD - always validate
python -m py_compile "path/to/file.py"
if ($LASTEXITCODE -eq 0) { echo "Syntax OK" }
```

✅ **DO**: Check for duplicate blocks before editing
```bash
# GOOD - check first
findstr /N "^\s*else:" "path/to/file.py"
```

✅ **DO**: Use consistent indentation (4 spaces)
```python
# GOOD - consistent
def function():
    if condition:
        do_something()
    else:
        do_other()
```

## Reference: Common Syntax Errors

| Error Type | Error Message | Fix |
|------------|---------------|-----|
| Duplicate `else` | `SyntaxError: invalid syntax` | Use `elif` instead |
| Indentation error | `IndentationError: unexpected indent` | Fix spacing |
| Undefined variable | `NameError: name 'xxx' is not defined` | Define before use |
| Unmatched bracket | `SyntaxError: closing parenthesis doesn't match` | Balance brackets |
| Invalid syntax | `SyntaxError: invalid syntax` | Check line and surrounding code |

## Debugging Syntax Errors

### Step 1: Check the error line
```bash
python -m py_compile "file.py"
# Error at line 123
```

### Step 2: Examine surrounding code
```python
# Read lines around the error
# Look for mismatched brackets, wrong indentation, duplicate blocks
```

### Step 3: Compare with working version
```bash
# If available, compare with working version
git diff file.py
```

### Step 4: Fix incrementally
- Change one thing at a time
- Validate after each change
- Test the specific functionality
