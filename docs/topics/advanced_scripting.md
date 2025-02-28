---
orphan: true
---

# Advanced Scripting

libtmux enables sophisticated scripting of tmux operations, allowing developers to create robust tools and workflows.

## Complex Window and Pane Layouts

Creating a grid layout with multiple panes:

```python
import libtmux
from libtmux.constants import PaneDirection

# Connect to the tmux server
server = libtmux.Server()

# Create or get session with proper handling for existing sessions
def get_clean_session(name):
    """Get a clean session, killing any existing windows if it already exists"""
    try:
        session = server.new_session(session_name=name)
    except libtmux.exc.TmuxSessionExists:
        session = server.sessions.get(session_name=name)
        # Clean up existing windows
        for window in session.windows:
            window.kill()
        # Create a new window
        window = session.new_window(window_name="main")
    else:
        window = session.active_window
    return session, window

# Create a 2x2 grid layout
def create_grid_layout(session_name="complex-layout"):
    session, window = get_clean_session(session_name)
    
    # Create a 2x2 grid of panes
    right_pane = window.split(direction=PaneDirection.Right)
    bottom_left = window.split(direction=PaneDirection.Below)
    
    # Select the right pane and split it
    window.select_pane(right_pane.pane_id)
    bottom_right = window.split(direction=PaneDirection.Below)
    
    # Send some test commands to the panes
    bottom_left.send_keys("echo 'Hello from bottom left'", enter=True)
    bottom_right.send_keys("echo 'Hello from bottom right'", enter=True)
    
    # Select layout
    window.select_layout("main-vertical")
    
    return session, window, [bottom_left, bottom_right]

# Example usage
session, window, panes = create_grid_layout()
print(f"Created session '{session.session_name}' with {len(window.panes)} panes")

# Clean up when done (uncomment if you want to kill the session)
# server.kill_session(session.session_id)
```

## Advanced Layouts and Window Management

Working with different window layouts and managing multiple windows:

```python
import libtmux
from libtmux.constants import PaneDirection

# Connect to the tmux server
server = libtmux.Server()

# Create or get session with proper handling for existing sessions
def get_clean_session(name):
    """Get a clean session, killing any existing windows if it already exists"""
    try:
        session = server.new_session(session_name=name)
    except libtmux.exc.TmuxSessionExists:
        session = server.sessions.get(session_name=name)
        # Clean up existing windows
        for window in session.windows:
            window.kill()
        # Create a new window
        window = session.new_window(window_name="main")
    else:
        window = session.active_window
    return session, window

# Create a session with multiple windows and layouts
def create_multi_window_session(session_name="advanced-layouts"):
    session, window = get_clean_session(session_name)
    
    # Create a multi-pane first window
    right_pane = window.split(direction=PaneDirection.Right)
    bottom_left = window.split(direction=PaneDirection.Below)
    
    # Select the right pane and split it
    window.select_pane(right_pane.pane_id)
    bottom_right = window.split(direction=PaneDirection.Below)
    
    # Try different layouts
    window.select_layout("main-vertical")  # Main pane on left, two on right
    
    # Create a second window for logs
    log_window = session.new_window(window_name="logs")
    
    # Switch between windows
    first_window = session.select_window(1)
    
    return session, first_window, log_window

# Example usage
session, first_window, log_window = create_multi_window_session()
print(f"Created session '{session.session_name}' with multiple windows")
print(f"First window has {len(first_window.panes)} panes")
print(f"Second window name: {log_window.window_name}")

# Clean up when done (uncomment if you want to kill the session)
# server.kill_session(session.session_id)
```

## Reactive Scripts

Creating scripts that monitor outputs and react to changes:

```python
import libtmux
import re
import time
from libtmux.constants import PaneDirection

# Connect to the tmux server
server = libtmux.Server()

# Create or get a clean session for reactive monitoring
def setup_reactive_monitoring(session_name="reactive-monitor"):
    """Set up a session for reactive monitoring with multiple panes"""
    try:
        session = server.new_session(session_name=session_name)
    except libtmux.exc.TmuxSessionExists:
        session = server.sessions.get(session_name=session_name) 
        # Clean up any existing windows
        for window in session.windows:
            window.kill()
        window = session.new_window(window_name="monitor")
    else:
        window = session.active_window
        window.rename_window("monitor")
    
    # Create source and monitoring panes
    source_pane = window.active_pane
    monitor_pane = window.split(direction=PaneDirection.Right)
    
    return session, window, source_pane, monitor_pane

def monitor_for_pattern(source_pane, monitor_pane, pattern="ERROR", interval=1.0, max_time=10):
    """Monitor source pane content for a pattern and react in the monitor pane"""
    start_time = time.time()
    pattern_re = re.compile(pattern)
    found = False
    
    # Generate some test output in source pane
    source_pane.send_keys("echo 'Starting test process...'", enter=True)
    source_pane.send_keys("for i in {1..5}; do echo \"Processing item $i\"; sleep 1; done", enter=True)
    source_pane.send_keys("echo 'ERROR: Something went wrong!'", enter=True)
    source_pane.send_keys("echo 'Finishing process'", enter=True)
    
    # Monitor for pattern
    while time.time() - start_time < max_time:
        content = source_pane.capture_pane()
        
        for line in content:
            if pattern_re.search(line):
                monitor_pane.send_keys(f"ALERT: Found pattern '{pattern}' in output!", enter=True)
                monitor_pane.send_keys(f"Taking corrective action...", enter=True)
                found = True
                break
        
        if found:
            break
            
        time.sleep(interval)
    
    return found

# Example usage
if __name__ == "__main__":
    session, window, source_pane, monitor_pane = setup_reactive_monitoring()
    
    print(f"Starting monitoring in session '{session.session_name}'")
    result = monitor_for_pattern(source_pane, monitor_pane)
    
    if result:
        print("Successfully detected and responded to the pattern")
    else:
        print("Pattern not found within the time limit")
```

## Deployment Monitoring

A practical example of using libtmux for deployment monitoring:

```python
import libtmux
from libtmux.constants import PaneDirection
import time

# Connect to the tmux server
server = libtmux.Server()

def setup_deployment_monitor(repo_name, branch="main", session_name="deployment"):
    """Set up a deployment monitoring environment with multiple windows"""
    try:
        session = server.new_session(session_name=session_name)
    except libtmux.exc.TmuxSessionExists:
        session = server.sessions.get(session_name=session_name)
        # Clean up existing windows
        for window in session.windows:
            window.kill()
    
    # Create a window for deployment logs
    deploy_window = session.new_window(window_name="deployment")
    
    # Window for API responses
    api_window = session.new_window(window_name="api-status")
    
    # Split the deployment window for different log types
    build_pane = deploy_window.active_pane
    test_pane = deploy_window.split(direction=PaneDirection.Right)
    
    # Rename the panes (command sent to each pane)
    build_pane.send_keys("# BUILD LOGS", enter=True)
    test_pane.send_keys("# TEST LOGS", enter=True)
    
    # Simulate deployment process
    build_pane.send_keys(f"echo 'Starting deployment of {repo_name}:{branch}'", enter=True)
    build_pane.send_keys("echo 'Building application...'", enter=True)
    
    # Wait a bit for "build" to complete
    time.sleep(1)
    
    test_pane.send_keys("echo 'Running tests...'", enter=True)
    for i in range(3):
        test_pane.send_keys(f"echo 'Test suite {i+1} passed'", enter=True)
        time.sleep(0.5)
    
    # Switch to API window and display results
    session.select_window("api-status")
    api_window.active_pane.send_keys("echo 'Deployment status: SUCCESS'", enter=True)
    api_window.active_pane.send_keys(f"echo 'Deployment ID: sample-{repo_name}-{int(time.time())}'", enter=True)
    
    # Return to the deployment window
    session.select_window("deployment")
    
    return session

# Example usage
if __name__ == "__main__":
    session = setup_deployment_monitor("my-app", "develop")
    print(f"Created deployment monitoring environment in session '{session.session_name}'")
```

## Working with Command Output

libtmux allows you to easily capture and process command output:

```python
import libtmux
import time
import re

# Connect to the tmux server
server = libtmux.Server()

def run_and_capture_command(command, session_name="command-output"):
    """Run a command in a tmux pane and capture its output"""
    try:
        session = server.new_session(session_name=session_name)
    except libtmux.exc.TmuxSessionExists:
        session = server.sessions.get(session_name=session_name)
        # Clean up existing windows
        for window in session.windows:
            window.kill()
        window = session.new_window(window_name="command")
    else:
        window = session.active_window
        window.rename_window("command")
    
    # Get the active pane
    pane = window.active_pane
    
    # Run the command
    pane.send_keys(command, enter=True)
    
    # Wait for the command to complete (in a real app, you might check for a prompt)
    time.sleep(1)
    
    # Capture the output
    output = pane.capture_pane()
    
    # Process the output (removing the command line itself)
    processed_output = [line for line in output if command not in line and line.strip()]
    
    return processed_output

def extract_info_from_output(output, pattern):
    """Extract information from command output using regex"""
    results = []
    regex = re.compile(pattern)
    
    for line in output:
        match = regex.search(line)
        if match:
            results.append(match.group(0))
    
    return results

# Example usage
if __name__ == "__main__":
    # Run some commands and capture output
    ls_output = run_and_capture_command("ls -la")
    df_output = run_and_capture_command("df -h")
    ps_output = run_and_capture_command("ps aux | grep python")
    
    # Extract information from the output
    files = extract_info_from_output(ls_output, r'\.py$')  # Find Python files
    disk_usage = extract_info_from_output(df_output, r'\d+%')  # Find disk usage percentages
    
    print("Python files found:", files)
    print("Disk usage percentages:", disk_usage)
```

## State Management

Saving and restoring session state:

```python
import libtmux
import json
import os

# Connect to the tmux server
server = libtmux.Server()

def save_state(session, state_file="tmux_state.json"):
    """Save the current state of a tmux session to a JSON file"""
    state = {
        "session_name": session.session_name,
        "windows": []
    }
    
    # Save information about each window
    for window in session.windows:
        window_info = {
            "window_name": window.window_name,
            "window_index": window.window_index,
            "panes": []
        }
        
        # Save information about each pane in the window
        for pane in window.panes:
            pane_info = {
                "pane_index": pane.pane_index,
                "current_path": pane.current_path
            }
            window_info["panes"].append(pane_info)
        
        state["windows"].append(window_info)
    
    # Write state to file (comment out for demonstration)
    # with open(state_file, 'w') as f:
    #     json.dump(state, f, indent=2)
    
    return state

def restore_session(state_data, server=None):
    """Restore a tmux session from saved state"""
    if server is None:
        server = libtmux.Server()
    
    session_name = state_data["session_name"]
    
    # Create or get the session
    try:
        session = server.new_session(session_name=session_name)
    except libtmux.exc.TmuxSessionExists:
        session = server.sessions.get(session_name=session_name)
        # Keep only the first window and remove others
        first_window = None
        for i, window in enumerate(session.windows):
            if i == 0:
                first_window = window
            else:
                window.kill()  
        session = server.sessions.get(session_name=session_name)
    
    # Create windows from saved state
    for window_info in state_data["windows"]:
        # Skip the first window if it already exists
        if window_info["window_index"] == "1" and session.windows:
            window = session.windows[0]
            window.rename_window(window_info["window_name"])
        else:
            # Create a new window
            window = session.new_window(window_name=window_info["window_name"])
        
        # Create additional panes if needed
        existing_pane_count = len(window.panes)
        needed_panes = len(window_info["panes"])
        
        # Create additional panes if needed
        for i in range(existing_pane_count, needed_panes):
            if i > 0:  # Skip the first pane which already exists
                window.split(direction=libtmux.constants.PaneDirection.Right)
    
    return session

# Example usage
if __name__ == "__main__":
    # Create a sample session
    try:
        session = server.new_session(session_name="state-example")
    except libtmux.exc.TmuxSessionExists:
        session = server.sessions.get(session_name="state-example")
    
    # Create a couple of windows
    main_window = session.active_window
    main_window.rename_window("main")
    
    # Create a logs window if it doesn't exist
    if "logs" not in [w.window_name for w in session.windows]:
        logs_window = session.new_window(window_name="logs")
    
    # Save the state
    state = save_state(session)
    print(f"Saved state for session {state['session_name']} with {len(state['windows'])} windows")
    
    # To restore:
    # restored_session = restore_session(state)
```

## Integration with External APIs

Integrating libtmux with external APIs for deployment monitoring:

```python
import libtmux
from libtmux.constants import PaneDirection
import time

# Connect to the tmux server
server = libtmux.Server()

def create_deployment_dashboard(repo_name, branch="main"):
    """Create a visual dashboard for deployment monitoring using tmux"""
    session_name = f"deploy-{repo_name}"
    
    # Create or get session
    try:
        session = server.new_session(session_name=session_name)
    except libtmux.exc.TmuxSessionExists:
        session = server.sessions.get(session_name=session_name)
        # Clean up existing windows
        for window in session.windows:
            window.kill()
    
    # Create dashboard window
    dashboard = session.new_window(window_name="dashboard")
    
    # Split into 4 panes
    # Top right: Build status
    build_pane = dashboard.split(direction=PaneDirection.Right)
    
    # Bottom left: Logs
    logs_pane = dashboard.active_pane
    logs_pane = logs_pane.split(direction=PaneDirection.Below)
    
    # Bottom right: Tests
    dashboard.select_pane(build_pane.pane_id)
    tests_pane = build_pane.split(direction=PaneDirection.Below)
    
    # In a real application, you would make API calls to your CI/CD system:
    # import requests
    # 
    # response = requests.get(
    #     f"https://api.github.com/repos/{owner}/{repo_name}/actions/runs",
    #     headers={"Authorization": f"token {github_token}"}
    # )
    # workflow_runs = response.json()["workflow_runs"]
    # latest_run = workflow_runs[0]
    
    # Instead, we'll simulate for this example:
    
    # Display info in each pane
    dashboard.select_pane(dashboard.panes[0].pane_id)
    dashboard.panes[0].send_keys("echo '=== DEPLOYMENT OVERVIEW ==='", enter=True)
    dashboard.panes[0].send_keys(f"echo 'Repository: {repo_name}'", enter=True)
    dashboard.panes[0].send_keys(f"echo 'Branch: {branch}'", enter=True)
    dashboard.panes[0].send_keys("echo 'Status: In Progress'", enter=True)
    
    # Build pane
    build_pane.send_keys("echo '=== BUILD STATUS ==='", enter=True)
    build_pane.send_keys("echo 'Build #123'", enter=True)
    for i in range(3):
        build_pane.send_keys(f"echo 'Building step {i+1}...'", enter=True)
        time.sleep(0.5)
    build_pane.send_keys("echo 'Build completed successfully'", enter=True)
    
    # Logs pane
    logs_pane.send_keys("echo '=== DEPLOYMENT LOGS ==='", enter=True)
    logs_pane.send_keys("echo 'Initializing deployment...'", enter=True)
    logs_pane.send_keys("echo 'Updating dependencies...'", enter=True)
    logs_pane.send_keys("echo 'Running database migrations...'", enter=True)
    logs_pane.send_keys("echo 'Restarting services...'", enter=True)
    
    # Tests pane
    tests_pane.send_keys("echo '=== TEST RESULTS ==='", enter=True)
    tests_pane.send_keys("echo 'Running test suite...'", enter=True)
    for i in range(3):
        tests_pane.send_keys(f"echo 'Test suite {i+1}: PASSED'", enter=True)
        time.sleep(0.5)
    tests_pane.send_keys("echo 'All tests passed!'", enter=True)
    
    # Update status in overview pane
    time.sleep(2)
    dashboard.select_pane(dashboard.panes[0].pane_id)
    dashboard.panes[0].send_keys("echo 'Status: DEPLOYED'", enter=True)
    
    return session

# Example usage
if __name__ == "__main__":
    session = create_deployment_dashboard("my-service", "production")
    print(f"Created deployment dashboard in session: {session.session_name}")
```

## Layout Management

Managing complex window layouts programmatically:

```python
import libtmux
from libtmux.constants import PaneDirection
import time

# Connect to the tmux server
server = libtmux.Server()

def create_complex_layout(session_name="layout-demo"):
    """Create a session with complex layout patterns"""
    try:
        session = server.new_session(session_name=session_name)
    except libtmux.exc.TmuxSessionExists:
        # Get the existing session
        session = server.sessions.get(session_name=session_name)
        # Clean up existing windows
        for window in session.windows:
            window.kill()
    
    # Create a window for our layout
    layout_window = session.new_window(window_name="complex-layout")
    
    # Create a 2x2 grid of panes
    right_pane = layout_window.split(direction=PaneDirection.Right)
    bottom_left = layout_window.split(direction=PaneDirection.Below)
    
    # Select the right pane and split it
    layout_window.select_pane(right_pane.pane_id)
    bottom_right = right_pane.split(direction=PaneDirection.Below)
    
    # Try different built-in layouts
    layouts = [
        "even-horizontal", 
        "even-vertical", 
        "main-horizontal", 
        "main-vertical", 
        "tiled"
    ]
    
    # Demonstrate different layouts
    for layout in layouts:
        # Display the layout name
        layout_window.select_pane(layout_window.panes[0].pane_id)
        layout_window.panes[0].send_keys(f"echo 'Switching to {layout}'", enter=True)
        
        # Apply the layout
        layout_window.select_layout(layout)
        
        # Send some test output to each pane to make it visible
        for i, pane in enumerate(layout_window.panes):
            pane.send_keys(f"echo 'Pane {i+1} in {layout} layout'", enter=True)
        
        # Pause to view the layout
        time.sleep(1)
    
    # Create a second window for other layouts
    custom_window = session.new_window(window_name="custom-layout")
    
    # Switch back to first window
    first_window = session.select_window(1)
    
    return session, first_window, custom_window

# Example usage
if __name__ == "__main__":
    session, first_window, custom_window = create_complex_layout()
    print(f"Created layout demonstration in session '{session.session_name}'")
    print(f"Window 1 index: {first_window.window_index}")
    print(f"Window 2 name: {custom_window.window_name}")
```

## Debugging Tips

Here are some useful tips for debugging libtmux scripts:

1. **Enable logging in your scripts** - This helps track what's happening during script execution:
   ```python
   import logging
   logging.basicConfig(
       level=logging.DEBUG,
       format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
       handlers=[logging.FileHandler('libtmux_debug.log'), logging.StreamHandler()]
   )
   ```

2. **Handle tmux session existence gracefully** - Always check if a session exists before creating or trying to use it:
   ```python
   try:
       session = server.new_session(session_name="debug-session")
   except libtmux.exc.TmuxSessionExists:
       session = server.sessions.get(session_name="debug-session")
   ```

3. **Check pane content effectively** - When checking for output in panes, be aware that the output may take time to appear:
   ```python
   def wait_for_output(pane, search_text, max_wait_time=10):
       """Wait for text to appear in pane output."""
       import time
       start_time = time.time()
       while time.time() - start_time < max_wait_time:
           output = pane.capture_pane()
           if any(search_text in line for line in output):
               return True
           time.sleep(0.5)
       return False
   ```

4. **Handle window and pane selection errors** - When selecting windows or panes, handle potential errors:
   ```python
   try:
       window = session.select_window(1)
   except libtmux.exc.LibTmuxException as e:
       print(f"Error selecting window: {e}")
       # Create the window if it doesn't exist
       window = session.new_window()
   ```

5. **Use context managers for session cleanup** - Implement context managers to ensure sessions are properly cleaned up:
   ```python
   class TmuxSessionContext:
       def __init__(self, session_name):
           self.server = libtmux.Server()
           self.session_name = session_name
           self.session = None
           
       def __enter__(self):
           try:
               self.session = self.server.new_session(session_name=self.session_name)
           except libtmux.exc.TmuxSessionExists:
               self.session = self.server.sessions.get(session_name=self.session_name)
           return self.session
           
       def __exit__(self, exc_type, exc_val, exc_tb):
           # Clean up if requested
           # self.server.kill_session(self.session_name)
           pass
   
   # Usage
   with TmuxSessionContext("debug-session") as session:
       window = session.new_window(window_name="debug")
       # Rest of your code...
   ```

6. **Inspect tmux directly** - For complex issues, you can use direct tmux commands to debug:
   ```python
   # Execute a tmux command and capture output
   def run_tmux_command(cmd):
       import subprocess
       result = subprocess.run(['tmux'] + cmd.split(), capture_output=True, text=True)
       return result.stdout.strip()
   
   # Example: List sessions directly
   sessions = run_tmux_command("list-sessions")
   print(f"Current tmux sessions: {sessions}")
   ```

By following these tips, you can make your libtmux scripts more robust and easier to debug.
