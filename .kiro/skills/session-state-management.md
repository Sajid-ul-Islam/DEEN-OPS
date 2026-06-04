# Session State Management Skill

## Overview

This skill helps prevent session state issues in Streamlit apps, particularly around state persistence, initialization timing, and rerun handling.

## Common Session State Issues

### 1. State Not Preserved Across Reruns

**Problem**: Session state is cleared or not preserved when `st.rerun()` is called

**Symptoms**:
- Chat messages disappear after sidebar button clicks
- Filter selections reset unexpectedly
- User preferences lost after page refresh

**Root Cause**: 
- Session state initialized AFTER rendering components that may trigger reruns
- State cleared by `st.session_state.clear()`
- State not properly checked before access

### 2. Duplicate State Initialization

**Problem**: Session state initialized multiple times, overwriting previous values

**Symptoms**:
- Chat history cleared on every page load
- User selections lost
- Unexpected default values

**Root Cause**:
- State initialization in multiple places
- No check for existing state before setting
- State set after rendering components

### 3. State Access Before Initialization

**Problem**: Session state accessed before being initialized

**Symptoms**:
- `KeyError` when accessing session state
- `NoneType` errors when using session state
- Unexpected default values used

**Root Cause**:
- State accessed before initialization
- No fallback values provided
- Initialization order incorrect

## Prevention Guidelines

### 1. Initialize State at Page Start

ALWAYS initialize critical session state at the START of page functions:

```python
# GOOD - Initialize at START
def render_page():
    # Initialize at the very start, before any rendering
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    # Now safe to use state
    for msg in st.session_state.messages:
        st.write(msg)
    
    # Render components
    render_sidebar()
```

❌ **DON'T**: Initialize after rendering
```python
# BAD - sidebar may rerun and reset state
render_sidebar()
if "messages" not in st.session_state:
    st.session_state.messages = []  # Too late!
```

### 2. Use Single Source of Truth

Initialize each piece of state in ONE place only:

```python
# GOOD - Single initialization
def render_page():
    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = [{"role": "assistant", "content": "Welcome!"}]
    
    if "pilot_reports" not in st.session_state:
        st.session_state.pilot_reports = []
    
    # Rest of page...
```

❌ **DON'T**: Multiple initializations
```python
# BAD - Multiple initializations cause conflicts
def render_page():
    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = []
    
    render_sidebar()  # May rerun
    
    # Second initialization - overwrites first!
    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = []
```

### 3. Check State Before Access

Always check if state exists before accessing:

```python
# GOOD - Safe access with fallback
messages = st.session_state.get("agent_messages", [])
for msg in messages:
    st.write(msg)
```

### 4. Lock Navigation During State Changes

When sidebar buttons trigger state changes, lock navigation:

```python
# GOOD - Lock navigation during state change
if st.button("Sync Data"):
    st.session_state["_nav_override"] = "Current Page"
    st.session_state.data = fetch_data()
    st.rerun()
```

### 5. Restore State After Processing

When chat input is processed, restore any locked navigation:

```python
# GOOD - Store and restore nav
elif prompt:
    # Store original nav
    original_nav = st.session_state.get("_nav_override")
    
    # Process input
    process_input()
    
    # Restore nav if needed
    if original_nav and "_nav_override" not in st.session_state:
        st.session_state["_nav_override"] = original_nav
```

## Case Study: Data Pilot Session State Issues

### Problem
User reported: "after inoputing anytext it is oppeng bacbk the lisve dashboard"

Investigation revealed:
1. `agent_messages` initialized twice (lines 331 and 353)
2. No navigation lock when sidebar buttons triggered reruns
3. No state preservation after chat input processing

### Solution Applied

**Fix 1: Consolidate Initialization**
```python
# BEFORE - Two initializations
def render_ai_pilot_page():
    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = [...]
    # ... more code ...
    if "agent_messages" not in st.session_state:  # DUPLICATE!
        st.session_state.agent_messages = [...]

# AFTER - Single initialization at start
def render_ai_pilot_page():
    # Lock navigation first
    if "_nav_override" not in st.session_state:
        st.session_state["_nav_override"] = ":material/rocket_launch: Data Pilot"
    
    # Initialize state
    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = [{"role": "assistant", "content": "..."}]
    
    if "pilot_reports" not in st.session_state:
        st.session_state.pilot_reports = []
    
    # Rest of page...
```

**Fix 2: Lock Navigation on Sidebar Reruns**
```python
# BEFORE - No navigation lock
if st.button("Sync"):
    sync_data()
    st.rerun()  # Navigation may change!

# AFTER - Navigation locked
if st.button("Sync"):
    st.session_state["_nav_override"] = ":material/rocket_launch: Data Pilot"
    sync_data()
    st.rerun()
```

**Fix 3: Restore Navigation After Chat Input**
```python
# BEFORE - No navigation restoration
elif prompt:
    process_input()
    st.session_state.agent_messages.append({"role": "assistant", "content": response})

# AFTER - Navigation restored
elif prompt:
    original_nav = st.session_state.get("_nav_override")
    process_input()
    
    st.session_state.agent_messages.append({"role": "assistant", "content": response})
    
    if original_nav and "_nav_override" not in st.session_state:
        st.session_state["_nav_override"] = original_nav
```

## Session State Best Practices

### 1. Naming Convention

Use clear, consistent naming:
- `agent_messages` - List of chat messages
- `pilot_reports` - List of generated reports
- `inv_priority_order` - List of outlet priorities
- `_nav_override` - Navigation lock (prefixed with underscore)

### 2. Initialization Pattern

Always use the same pattern:
```python
# Pattern
if "state_name" not in st.session_state:
    st.session_state.state_name = default_value
```

### 3. Access Pattern

Always use safe access:
```python
# Get with fallback
messages = st.session_state.get("agent_messages", [])

# Or check first
if "agent_messages" in st.session_state:
    messages = st.session_state.agent_messages
```

### 4. Modification Pattern

When modifying lists/dicts:
```python
# Don't overwrite - modify in place
if "messages" not in st.session_state:
    st.session_state.messages = []
st.session_state.messages.append(new_message)  # Modify in place

# Don't do this
st.session_state.messages = st.session_state.messages + [new_message]  # Overwrite
```

## Debugging Session State Issues

### Step 1: Check State Contents

Add debug output to see current state:
```python
st.write(st.session_state)
```

### Step 2: Check Initialization Order

Verify state is initialized before use:
```python
# Check if state exists
if "messages" in st.session_state:
    st.write(f"Messages: {len(st.session_state.messages)}")
else:
    st.write("Messages not initialized!")
```

### Step 3: Check Rerun Impact

Test if state persists across reruns:
```python
# Click a button that triggers rerun
# Check if state is preserved
```

## Anti-Patterns to Avoid

❌ **DON'T**: Initialize state after rendering components
```python
# BAD - sidebar rerun may reset state
render_sidebar()
if "messages" not in st.session_state:
    st.session_state.messages = []
```

❌ **DON'T**: Initialize state multiple times
```python
# BAD - overwrites previous values
def func1():
    if "messages" not in st.session_state:
        st.session_state.messages = []

def func2():
    if "messages" not in st.session_state:  # Second check!
        st.session_state.messages = []
```

❌ **DON'T**: Access state without checking
```python
# BAD - may raise KeyError
for msg in st.session_state.messages:  # If not initialized!
    st.write(msg)
```

✅ **DO**: Initialize at page start, lock navigation, use safe access
```python
# GOOD - All best practices
def render_page():
    # Lock navigation
    if "_nav_override" not in st.session_state:
        st.session_state["_nav_override"] = "Current Page"
    
    # Initialize state at START
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    # Safe access
    for msg in st.session_state.get("messages", []):
        st.write(msg)
```

## Reference: Session State in Data Pilot

### Critical State Variables
| Variable | Type | Description |
|----------|------|-------------|
| `agent_messages` | List[Dict] | Chat history |
| `pilot_reports` | List[Dict] | Generated reports |
| `pilot_last_intent` | str | Last detected intent |
| `pilot_uploaded_df` | DataFrame | Uploaded data |
| `pilot_pathao_tracking_df` | DataFrame | Pathao tracking data |
| `pilot_uploader_key` | int | File uploader key |
| `inv_priority_order` | List[str] | Outlet priority order |

### Initialization Pattern
```python
def render_ai_pilot_page():
    # Navigation lock (critical for stability)
    if "_nav_override" not in st.session_state:
        st.session_state["_nav_override"] = ":material/rocket_launch: Data Pilot"
    
    # Chat state (critical for UX)
    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = [{"role": "assistant", "content": "..."}]
    
    # Report state (critical for UX)
    if "pilot_reports" not in st.session_state:
        st.session_state.pilot_reports = []
    
    # Inventory state (critical for feature)
    if "inv_priority_order" not in st.session_state:
        st.session_state.inv_priority_order = ["Ecom-Mirpur", "Wari", "Cumilla", "Sylhet"]
```

### Sidebar Button Pattern
```python
# All sidebar buttons that call st.rerun() must lock navigation
if st.button("Action"):
    st.session_state["_nav_override"] = ":material/rocket_launch: Data Pilot"
    process_action()
    st.rerun()  # Navigation is locked
```

### Chat Input Pattern
```python
elif prompt:
    # Store original nav
    original_nav = st.session_state.get("_nav_override")
    
    # Process input
    process_input()
    
    # Restore nav if needed
    if original_nav and "_nav_override" not in st.session_state:
        st.session_state["_nav_override"] = original_nav
    
    # Add to history
    st.session_state.agent_messages.append({"role": "assistant", "content": response})
```
