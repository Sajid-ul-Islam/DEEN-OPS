# Navigation Stability Skill

## Overview

This skill helps prevent navigation issues in Streamlit apps, particularly around sidebar reruns and session state management.

## Problem: Navigation Changes Unexpectedly

### Symptoms
- User stays on a page (e.g., Data Pilot), but after interacting with sidebar buttons or submitting chat input, the app navigates back to the Live Dashboard
- Sidebar button clicks trigger page reruns that affect navigation state
- `st.session_state` changes unexpectedly after sidebar reruns

### Root Causes
1. **Sidebar reruns** - When `st.rerun()` is called from sidebar buttons, the entire page restarts
2. **Session state cleared** - `st.session_state.clear()` or similar operations clear all state
3. **Navigation override conflicts** - `_nav_override` being set/cleared inconsistently
4. **Duplicate code blocks** - Multiple `else:` blocks causing syntax errors
5. **Incorrect indentation** - Code blocks with inconsistent spacing

## Prevention Guidelines

### 1. Lock Navigation During Critical Operations

Always lock navigation when sidebar buttons trigger `st.rerun()`:

```python
# BEFORE (problematic):
if st.button("Do something"):
    process_data()
    st.rerun()

# AFTER (fixed):
if st.button("Do something"):
    # Lock navigation to current page
    st.session_state["_nav_override"] = "🚀 Data Pilot"
    process_data()
    st.rerun()
```

### 2. Preserve Session State Across Reruns

Initialize critical session state at the START of page render functions:

```python
def render_page():
    # Initialize at START, not after rendering other components
    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = []
    
    # Render sidebar (may trigger reruns)
    render_sidebar()
    
    # Now safe to use session state
    for msg in st.session_state.agent_messages:
        st.write(msg)
```

### 3. Restore Navigation After Processing

When chat input is processed, restore any navigation override:

```python
elif prompt:
    # Store original nav state
    original_nav = st.session_state.get("_nav_override")
    
    # Process input...
    process_input()
    
    # Restore nav if it was set
    if original_nav and "_nav_override" not in st.session_state:
        st.session_state["_nav_override"] = original_nav
```

### 4. Check Navigation Lock at Page Start

Add a lock at the start of page functions:

```python
def render_ai_pilot_page():
    # Lock navigation to Data Pilot to prevent sidebar reruns from changing it
    if "_nav_override" in st.session_state and st.session_state["_nav_override"] != "🚀 Data Pilot":
        st.session_state["_nav_override"] = "🚀 Data Pilot"
    
    # Rest of page rendering...
```

### 5. Avoid Duplicate Code Blocks

When editing files, verify:
- No duplicate `if`/`else` blocks at the same level
- Consistent indentation across all code blocks
- No references to undefined variables in code blocks

### 6. Syntax Validation

Always verify Python syntax after edits:

```bash
python -m py_compile "path/to/file.py"
```

## Case Study: Data Pilot Navigation Issue

### Problem
User reported: "after inoputing anytext it is oppeng bacbk the lisve dashboard"

### Investigation
1. Checked `data_pilot.py` for navigation-related code
2. Found sidebar buttons calling `st.rerun()` without navigation locks
3. Found duplicate session state initialization causing conflicts
4. Found no mechanism to preserve navigation state during reruns

### Solution Applied
1. Added `_nav_override` lock at page start
2. Added `_nav_override` lock before all sidebar button reruns (4 buttons)
3. Added `_nav_override` restoration after chat input processing
4. Consolidated session state initialization to single location at page start
5. Removed duplicate code blocks in `dashboard_output.py`

### Files Modified
- `src/pages/data_pilot.py` - Navigation locks, session state preservation
- `src/pages/dashboard_output.py` - Removed duplicate else blocks
- `src/pages/inventory_distribution.py` - Added else clause for missing default files

## Prevention Checklist

When making changes to Streamlit pages, verify:
- [ ] Sidebar buttons that call `st.rerun()` also set `_nav_override`
- [ ] Session state is initialized at page start, not after other components
- [ ] No duplicate code blocks or indentation issues
- [ ] Python syntax is valid (`py_compile` check passes)
- [ ] Navigation lock added to page function
- [ ] Chat input processing restores navigation state

## Reference: Navigation Flow

```
1. User clicks sidebar button → triggers st.rerun()
2. Page restarts → sidebar renders first
3. Sidebar button sets _nav_override → prevents nav change
4. Main content renders → chat input available
5. User submits message → stores original nav
6. Response processed → restores nav if needed
7. Page completes → user stays on Data Pilot
```

## Anti-Patterns to Avoid

❌ **DON'T**: Set session state after sidebar rendering
```python
# BAD - sidebar may rerun, resetting state
render_sidebar()
if "agent_messages" not in st.session_state:
    st.session_state.agent_messages = []  # Too late!
```

❌ **DON'T**: Call `st.rerun()` without navigation lock
```python
# BAD - may change navigation unexpectedly
if st.button("Sync"):
    sync_data()
    st.rerun()  # Navigation may change!
```

❌ **DON'T**: Have duplicate code blocks
```python
# BAD - causes syntax errors
if condition:
    do_something()
else:
    do_something_else()
else:  # Syntax error!
    do_third_thing()
```

✅ **DO**: Lock navigation, initialize state early, single code paths
```python
# GOOD - stable and predictable
def render_page():
    # Lock navigation
    if "_nav_override" not in st.session_state:
        st.session_state["_nav_override"] = "Current Page"
    
    # Initialize state at start
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    # Render sidebar (may rerun)
    render_sidebar()
    
    # Main content
    for msg in st.session_state.messages:
        st.write(msg)
```
