---
orphan: true
---

# Advanced Scripting

libtmux enables sophisticated scripting of tmux operations, allowing developers to create robust tools and workflows.

## Complex Window and Pane Layouts

You can create intricate layouts with precise control over window and pane placement:

```python
import libtmux

server = libtmux.Server()
session = server.new_session(session_name="complex-layout")

# Create main window
main = session.new_window(window_name="main-window")

# Create side pane (vertical split)
side_pane = main.split_window(vertical=True)

# Create bottom pane (horizontal split from main pane)
bottom_pane = main.attached_pane.split_window(vertical=False)

# Create a grid layout in another window
grid_window = session.new_window(window_name="grid")
top_left = grid_window.attached_pane
top_right = top_left.split_window(vertical=True)
bottom_left = top_left.split_window(vertical=False)
bottom_right = top_right.split_window(vertical=False)

# Now you can send commands to each pane
top_left.send_keys("echo 'Top Left'", enter=True)
top_right.send_keys("echo 'Top Right'", enter=True)
bottom_left.send_keys("echo 'Bottom Left'", enter=True)
bottom_right.send_keys("echo 'Bottom Right'", enter=True)
```

## Reactive Scripts

Create scripts that react to tmux events or monitor state:

```python
import libtmux
import time

server = libtmux.Server()
session = server.find_where({"session_name": "monitored-session"})

if not session:
    print("Session not found!")
    exit(1)

def monitor_pane_count():
    """Monitor the number of panes and react to changes"""
    initial_pane_count = len(session.list_windows()[0].list_panes())
    print(f"Starting monitor with {initial_pane_count} panes")
    
    while True:
        time.sleep(5)  # Check every 5 seconds
        current_pane_count = len(session.list_windows()[0].list_panes())
        
        if current_pane_count > initial_pane_count:
            print(f"New pane detected! ({current_pane_count} total)")
            # React to new pane - perhaps log it or configure it
            newest_pane = session.list_windows()[0].list_panes()[-1]
            newest_pane.send_keys("echo 'This pane was auto-configured'", enter=True)
            
        elif current_pane_count < initial_pane_count:
            print(f"Pane closed! ({current_pane_count} remaining)")
            # React to closed pane
            
        initial_pane_count = current_pane_count

# Use in a script
if __name__ == "__main__":
    try:
        monitor_pane_count()
    except KeyboardInterrupt:
        print("Monitoring stopped")
```

## Working with Command Output

libtmux allows you to easily capture and process command output:

```python
import libtmux

server = libtmux.Server()
session = server.new_session(session_name="command-output")
window = session.attached_window

# Send a command and capture its output
window.send_keys("ls -la", enter=True)

# Wait for command to complete
import time
time.sleep(1)

# Capture the pane content
output = window.attached_pane.capture_pane()

# Process the output
for line in output:
    if "total " in line:
        print(f"Directory size summary: {line}")
        break
        
# Execute a tmux command directly and process its result
running_sessions = server.cmd("list-sessions", "-F", "#{session_name}").stdout
print(f"Current sessions: {running_sessions}")
```

## State Management

Implement state tracking for your tmux sessions:

```python
import libtmux
import json
import os
from datetime import datetime

class TmuxStateManager:
    def __init__(self, state_file="~/.tmux_state.json"):
        self.state_file = os.path.expanduser(state_file)
        self.server = libtmux.Server()
        self.state = self._load_state()
        
    def _load_state(self):
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r') as f:
                return json.load(f)
        return {"sessions": {}, "last_update": None}
        
    def _save_state(self):
        self.state["last_update"] = datetime.now().isoformat()
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)
            
    def update_session_state(self, session_name):
        """Record information about a session"""
        session = self.server.find_where({"session_name": session_name})
        if not session:
            return False
            
        windows_info = []
        for window in session.windows:
            panes_info = []
            for pane in window.panes:
                panes_info.append({
                    "pane_id": pane.pane_id,
                    "pane_index": pane.pane_index,
                    "current_path": pane.current_path,
                    "current_command": pane.current_command
                })
                
            windows_info.append({
                "window_id": window.window_id,
                "window_name": window.window_name,
                "panes": panes_info
            })
            
        self.state["sessions"][session_name] = {
            "session_id": session.session_id,
            "created_at": datetime.now().isoformat(),
            "windows": windows_info
        }
        
        self._save_state()
        return True
        
    def restore_session(self, session_name):
        """Attempt to restore a session based on saved state"""
        if session_name not in self.state["sessions"]:
            return False
            
        saved_session = self.state["sessions"][session_name]
        # Implementation of session restoration logic here
        
        return True
```

## Integration with External APIs

Combine libtmux with external APIs for powerful automation:

```python
import libtmux
import requests
import json

def deploy_and_monitor(repo_name, branch="main"):
    # Start a new deployment session
    server = libtmux.Server()
    session = server.new_session(session_name=f"deploy-{repo_name}")
    
    # Window for deployment log
    deploy_window = session.attached_window
    deploy_window.rename_window("deployment")
    
    # Window for API responses
    api_window = session.new_window(window_name="api-status")
    
    # Trigger deployment via API
    deploy_window.send_keys(f"echo 'Starting deployment of {repo_name}:{branch}'", enter=True)
    response = requests.post(
        "https://api.example.com/deployments",
        json={"repository": repo_name, "branch": branch},
        headers={"Authorization": "Bearer YOUR_TOKEN"}
    )
    
    # Display API response
    deployment_id = response.json().get("deployment_id")
    api_window.send_keys(f"echo 'Deployment triggered: {deployment_id}'", enter=True)
    
    # Poll status API
    for _ in range(10):  # Check 10 times
        status_response = requests.get(
            f"https://api.example.com/deployments/{deployment_id}",
            headers={"Authorization": "Bearer YOUR_TOKEN"}
        )
        status = status_response.json().get("status")
        api_window.send_keys(f"echo 'Current status: {status}'", enter=True)
        
        if status in ["complete", "failed"]:
            break
            
        # Wait before checking again
        import time
        time.sleep(30)
    
    # Final deployment result
    deploy_window.send_keys(f"echo 'Deployment {deployment_id} finished with status: {status}'", enter=True)
    
    return deployment_id, status
```

## Debugging Tips

When scripting with libtmux, consider these debugging approaches:

1. Use `session.cmd('display-message', 'Debug message')` to display messages in the tmux client
2. Capture pane content with `pane.capture_pane()` to see the current state
3. Use Python's logging module to track script execution 
4. Add print statements and redirect your script's output to a file for later inspection
5. When testing complex scripts, use a dedicated testing session to avoid affecting your main workflow
```
