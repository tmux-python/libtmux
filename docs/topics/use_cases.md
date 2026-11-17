---
orphan: true
---

# Use Cases

libtmux provides a powerful abstraction layer for tmux, enabling a wide range of use cases beyond manual terminal management. This document explores practical applications and real-world scenarios where libtmux shines.

## DevOps and Infrastructure

### CI/CD Pipeline Integration

libtmux can be integrated into Continuous Integration and Continuous Deployment pipelines to:

- Create isolated environments for running tests
- Capture test output and logs
- Provide a persistent terminal interface for long-running processes
- Execute deployment steps in parallel

```python
>>> import libtmux
>>> from libtmux.constants import PaneDirection
>>> 
>>> def setup_test_environment():
...     server = libtmux.Server()
...     try:
...         session = server.new_session(session_name="ci-tests")
...     except libtmux.exc.TmuxSessionExists:
...         session = server.sessions.get(session_name="ci-tests")
...         # Clean up existing windows
...         for window in session.windows:
...             window.kill()
...         # Create a new window
...         session.new_window(window_name="main")
...     
...     # Create windows for different test suites
...     unit_tests = session.active_window
...     unit_tests.rename_window("unit-tests")
...     integration_tests = session.new_window(window_name="integration-tests")
...     ui_tests = session.new_window(window_name="ui-tests")
...     
...     # The following would run tests in parallel (commented out for doctest)
...     # unit_tests.send_keys("cd /path/to/project && pytest tests/unit", enter=True)
...     # integration_tests.send_keys("cd /path/to/project && pytest tests/integration", enter=True)
...     # ui_tests.send_keys("cd /path/to/project && pytest tests/ui", enter=True)
...     
...     return session
>>> 
>>> # Example usage (not executed in doctest)
>>> # test_session = setup_test_environment()
>>> # print(f"Created test session with {len(test_session.windows)} windows")
```

### Server Management

Automate administrative tasks across multiple servers:

```python
>>> import libtmux
>>> from libtmux.constants import PaneDirection
>>> 
>>> def monitor_server_cluster(servers):
...     """Create a tmux dashboard to monitor multiple servers at once"""
...     server = libtmux.Server()
...     try:
...         session = server.new_session(session_name="server-cluster")
...     except libtmux.exc.TmuxSessionExists:
...         session = server.sessions.get(session_name="server-cluster")
...         # Clean up existing windows
...         for window in session.windows:
...             window.kill()
...         # Create a new window
...         session.new_window(window_name="main")
...     
...     # Create initial window
...     first_window = session.active_window
...     first_window.rename_window(servers[0])
...     
...     # The following commands would connect to servers (commented out for doctest)
...     # first_window.send_keys(f"ssh admin@{servers[0]}", enter=True)
...     # first_window.send_keys("htop", enter=True)
...     
...     # Create windows for other servers
...     for server_name in servers[1:]:
...         window = session.new_window(window_name=server_name)
...         # window.send_keys(f"ssh admin@{server_name}", enter=True)
...         # window.send_keys("htop", enter=True)
...     
...     return session
>>> 
>>> # Example usage (not executed in doctest)
>>> # servers = ["web-server-1", "db-server-1", "cache-server-1"]
>>> # cluster_session = monitor_server_cluster(servers)
```

## Development Workflows

### Project-Specific Environments

Create custom development environments for different projects:

```python
>>> import libtmux
>>> from libtmux.constants import PaneDirection
>>> 
>>> def python_dev_environment(project_path):
...     server = libtmux.Server()
...     try:
...         session = server.new_session(session_name="python-dev")
...     except libtmux.exc.TmuxSessionExists:
...         session = server.sessions.get(session_name="python-dev")
...         # Clean up existing windows
...         for window in session.windows:
...             window.kill()
...         # Create a new window
...         session.new_window(window_name="main")
...     
...     # Editor window
...     editor = session.active_window
...     editor.rename_window("editor")
...     
...     # The following commands are commented out for doctest
...     # editor.send_keys(f"cd {project_path} && vim .", enter=True)
...     
...     # Terminal window with virtual environment
...     terminal = session.new_window(window_name="terminal")
...     # terminal.send_keys(f"cd {project_path}", enter=True)
...     # terminal.send_keys("source venv/bin/activate", enter=True)
...     
...     # Test window
...     test = session.new_window(window_name="tests")
...     # test.send_keys(f"cd {project_path}", enter=True)
...     # test.send_keys("source venv/bin/activate", enter=True)
...     # test.send_keys("pytest -xvs", enter=True)
...     
...     # Documentation window
...     docs = session.new_window(window_name="docs")
...     # docs.send_keys(f"cd {project_path}/docs", enter=True)
...     # docs.send_keys("make html", enter=True)
...     
...     return session
>>> 
>>> # Example usage (not executed in doctest)
>>> # dev_session = python_dev_environment("/path/to/my-project")
>>> # print(f"Created dev environment with {len(dev_session.windows)} windows")
```

### Pair Programming

Facilitate pair programming sessions:

```python
>>> import libtmux
>>> from libtmux.constants import PaneDirection
>>> 
>>> def pair_programming_session(project_path, partner_ip=None):
...     server = libtmux.Server()
...     try:
...         session = server.new_session(session_name="pair-programming")
...     except libtmux.exc.TmuxSessionExists:
...         session = server.sessions.get(session_name="pair-programming")
...         # Clean up existing windows
...         for window in session.windows:
...             window.kill()
...         # Create a new window
...         session.new_window(window_name="main")
...     
...     # Setup main editor window
...     main = session.active_window
...     main.rename_window("code")
...     
...     # The following commands are commented out for doctest
...     # main.send_keys(f"cd {project_path}", enter=True)
...     # main.send_keys("vim .", enter=True)
...     
...     # Setup terminal for running commands
...     terminal = session.new_window(window_name="terminal")
...     # terminal.send_keys(f"cd {project_path}", enter=True)
...     
...     # Setup tests window
...     tests = session.new_window(window_name="tests")
...     # tests.send_keys(f"cd {project_path}", enter=True)
...     # tests.send_keys("npm test -- --watch", enter=True)
...     
...     # If remote pairing, setup SSH
...     if partner_ip:
...         # Allow SSH connections to this tmux session
...         session.cmd("set-option", "allow-rename", "off")
...         session.cmd("set-option", "mouse", "on")
...         
...         # Instructions for partner
...         notes = session.new_window(window_name="notes")
...         # notes.send_keys(f"echo 'To join this session, run: ssh user@{partner_ip} -t \"tmux attach -t pair-programming\"'", enter=True)
...     
...     return session
>>> 
>>> # Example usage (not executed in doctest)
>>> # pp_session = pair_programming_session("/path/to/project", "192.168.1.100")
```

## Data Science and Analytics

### Data Processing Workflows

Manage complex data processing pipelines:

```python
>>> import libtmux
>>> from libtmux.constants import PaneDirection
>>> 
>>> def data_processing_pipeline(data_path):
...     server = libtmux.Server()
...     try:
...         session = server.new_session(session_name="data-pipeline")
...     except libtmux.exc.TmuxSessionExists:
...         session = server.sessions.get(session_name="data-pipeline")
...         # Clean up existing windows
...         for window in session.windows:
...             window.kill()
...         # Create a new window
...         session.new_window(window_name="main")
...     
...     # Data preparation
...     prep = session.active_window
...     prep.rename_window("preparation")
...     
...     # The following commands are commented out for doctest
...     # prep.send_keys(f"cd {data_path}", enter=True)
...     # prep.send_keys("python prepare_data.py", enter=True)
...     
...     # Model training
...     train = session.new_window(window_name="training")
...     # train.send_keys(f"cd {data_path}", enter=True)
...     # train.send_keys("python train_model.py", enter=True)
...     
...     # Monitoring training with split panes
...     monitor = session.new_window(window_name="monitor")
...     # monitor.send_keys(f"cd {data_path}", enter=True)
...     # monitor.send_keys("nvidia-smi", enter=True)
...     
...     # Create a second pane for monitoring system resources
...     system_pane = monitor.split(direction=PaneDirection.Right)
...     # system_pane.send_keys("htop", enter=True)
...     
...     # Create a third pane for logs
...     log_pane = system_pane.split(direction=PaneDirection.Below)
...     # log_pane.send_keys(f"tail -f {data_path}/logs/training.log", enter=True)
...     
...     return session
>>> 
>>> # Example usage (not executed in doctest)
>>> # pipeline_session = data_processing_pipeline("/path/to/data")
```

## Education and Presentation

### Live Coding Demonstrations

Create environments for teaching and presenting code:

```python
>>> import libtmux
>>> from libtmux.constants import PaneDirection
>>> 
>>> def teaching_session(course_materials_path):
...     server = libtmux.Server()
...     try:
...         session = server.new_session(session_name="teaching")
...     except libtmux.exc.TmuxSessionExists:
...         session = server.sessions.get(session_name="teaching")
...         # Clean up existing windows
...         for window in session.windows:
...             window.kill()
...         # Create a new window
...         session.new_window(window_name="main")
...     
...     # Main presentation window
...     main = session.active_window
...     main.rename_window("slides")
...     
...     # The following commands are commented out for doctest
...     # main.send_keys(f"cd {course_materials_path}/slides", enter=True)
...     # main.send_keys("mdp presentation.md", enter=True)
...     
...     # Code examples window
...     code = session.new_window(window_name="code")
...     # code.send_keys(f"cd {course_materials_path}/examples", enter=True)
...     # code.send_keys("vim -M main.py", enter=True)  # Open in read-only mode for safety
...     
...     # Live coding window
...     live = session.new_window(window_name="live-coding")
...     # live.send_keys(f"cd {course_materials_path}/workspace", enter=True)
...     
...     # Exercise window for students to follow along
...     exercise = session.new_window(window_name="exercise")
...     # exercise.send_keys(f"cd {course_materials_path}/exercises", enter=True)
...     # exercise.send_keys("vim exercise_01.py", enter=True)
...     
...     return session
>>> 
>>> # Example usage (not executed in doctest)
>>> # teaching = teaching_session("/path/to/course")
```

## System Administration

### Log Monitoring Dashboard

Create a comprehensive log monitoring system:

```python
>>> import libtmux
>>> from libtmux.constants import PaneDirection
>>> import os  # Used in the example
>>> 
>>> def log_monitoring_dashboard(log_paths):
...     server = libtmux.Server()
...     try:
...         session = server.new_session(session_name="log-monitor")
...     except libtmux.exc.TmuxSessionExists:
...         session = server.sessions.get(session_name="log-monitor")
...         # Clean up existing windows
...         for window in session.windows:
...             window.kill()
...         # Create a new window
...         session.new_window(window_name="main")
...     
...     # Create first window with first log
...     window = session.active_window
...     window.rename_window(os.path.basename(log_paths[0]))
...     
...     # The following commands are commented out for doctest
...     # window.send_keys(f"tail -f {log_paths[0]}", enter=True)
...     
...     # Create windows for remaining logs
...     for log_path in log_paths[1:]:
...         log_name = os.path.basename(log_path)
...         log_window = session.new_window(window_name=log_name)
...         # log_window.send_keys(f"tail -f {log_path}", enter=True)
...     
...     # Create a summary window
...     summary = session.new_window(window_name="summary")
...     summary_pane = summary.active_pane
...     
...     # Split into multiple panes for different summaries
...     error_pane = summary_pane.split(direction=PaneDirection.Right)
...     warning_pane = summary_pane.split(direction=PaneDirection.Below)
...     
...     # Set up grep commands to highlight different log levels
...     # summary_pane.send_keys(f"tail -f {' '.join(log_paths)} | grep -i 'ERROR' --color=always", enter=True)
...     # error_pane.send_keys(f"tail -f {' '.join(log_paths)} | grep -i 'WARN' --color=always", enter=True)
...     # warning_pane.send_keys(f"tail -f {' '.join(log_paths)} | grep -i 'INFO' --color=always", enter=True)
...     
...     return session
>>> 
>>> # Example usage (not executed in doctest)
>>> # logs = ["/var/log/system.log", "/var/log/application.log", "/var/log/errors.log"]
>>> # log_session = log_monitoring_dashboard(logs)
```

## Additional Use Cases

- **Automated testing environments**: Create isolated environments for running tests with visual feedback
- **Remote server management**: Control multiple remote machines through a single interface
- **Long-running process management**: Start, monitor, and control processes that need to run for extended periods
- **Distributed system management**: Coordinate actions across multiple systems
- **Interactive documentation**: Create interactive tutorials that guide users through complex procedures
- **Recovery systems**: Build automated recovery procedures for system failures

## DevOps Workflows

Create an infrastructure management dashboard with multiple environments:

```python
import libtmux
from libtmux.constants import PaneDirection
import time

# Connect to the tmux server
server = libtmux.Server()

def create_infra_dashboard(session_name="infra-management"):
    """Create an infrastructure management dashboard"""
    try:
        session = server.new_session(session_name=session_name)
    except libtmux.exc.TmuxSessionExists:
        session = server.sessions.get(session_name=session_name)
        # Clean up existing windows
        for window in session.windows:
            window.kill()
    
    # Create a window for each environment
    staging_window = session.new_window(window_name="staging")
    production_window = session.new_window(window_name="production")
    monitoring_window = session.new_window(window_name="monitoring")

    # Setup staging window with multiple panes
    staging_pane = staging_window.active_pane
    staging_pane.send_keys("echo 'Staging Environment Control'", enter=True)
    
    # Split the staging window for different components
    db_pane = staging_window.split(direction=PaneDirection.Right)
    db_pane.send_keys("echo 'Database Management'", enter=True)
    
    app_pane = staging_pane.split(direction=PaneDirection.Below)
    app_pane.send_keys("echo 'Application Deployment'", enter=True)
    
    # Setup production window
    prod_pane = production_window.active_pane
    prod_pane.send_keys("echo 'Production Environment Control'", enter=True)
    
    deploy_pane = production_window.split(direction=PaneDirection.Right)
    deploy_pane.send_keys("echo 'Deployment Pipeline'", enter=True)
    
    # Setup monitoring with multiple panes
    monitor_pane = monitoring_window.active_pane
    monitor_pane.send_keys("echo 'System Monitoring'", enter=True)
    
    log_pane = monitoring_window.split(direction=PaneDirection.Right)
    log_pane.send_keys("echo 'Log Monitoring'", enter=True)
    
    alert_pane = monitor_pane.split(direction=PaneDirection.Below)
    alert_pane.send_keys("echo 'Alerts Dashboard'", enter=True)
    
    return session, staging_window, production_window, monitoring_window

# Example usage
if __name__ == "__main__":
    session, staging, production, monitoring = create_infra_dashboard()
    print(f"Created infrastructure dashboard in session: {session.session_name}")
    print(f"Windows: {[w.window_name for w in session.windows]}")
```

## Development Workflows

Set up a comprehensive development environment for any project:

```python
import libtmux
from libtmux.constants import PaneDirection
import os

# Connect to the tmux server
server = libtmux.Server()

def setup_dev_environment(project_name, project_dir=None):
    """
    Set up a development environment with windows for:
    - Code editing
    - Testing
    - Version control
    - Running the application
    """
    if project_dir is None:
        project_dir = os.path.expanduser(f"~/projects/{project_name}")
    
    try:
        session = server.new_session(session_name=project_name)
    except libtmux.exc.TmuxSessionExists:
        session = server.sessions.get(session_name=project_name)
        # Clean up existing windows
        for window in session.windows:
            window.kill()
    
    # Set up windows for different development tasks
    code_window = session.new_window(window_name="code")
    test_window = session.new_window(window_name="tests")
    git_window = session.new_window(window_name="git")
    run_window = session.new_window(window_name="run")

    # Set up the code editing window with split panes
    editor_pane = code_window.active_pane
    
    # Navigate to project directory in all panes
    editor_pane.send_keys(f"cd {project_dir}", enter=True)
    editor_pane.send_keys("echo 'Code Editor'", enter=True)
    editor_pane.send_keys("vim .", enter=True)

    # File browser on the side
    file_pane = code_window.split(direction=PaneDirection.Right, size=25)
    file_pane.send_keys(f"cd {project_dir}", enter=True)
    file_pane.send_keys("echo 'File Browser'", enter=True)
    file_pane.send_keys("ls -la", enter=True)

    # Terminal below
    terminal_pane = editor_pane.split(direction=PaneDirection.Below, size=10)
    terminal_pane.send_keys(f"cd {project_dir}", enter=True)
    terminal_pane.send_keys("echo 'Terminal'", enter=True)

    # Setup test window
    test_pane = test_window.active_pane
    test_pane.send_keys(f"cd {project_dir}", enter=True)
    test_pane.send_keys("echo 'Running tests...'", enter=True)
    
    # Add test output pane
    test_output = test_window.split(direction=PaneDirection.Right)
    test_output.send_keys(f"cd {project_dir}", enter=True)
    test_output.send_keys("echo 'Test output will appear here'", enter=True)

    # Setup git window
    git_pane = git_window.active_pane
    git_pane.send_keys(f"cd {project_dir}", enter=True)
    git_pane.send_keys("echo 'Git status'", enter=True)
    git_pane.send_keys("git status", enter=True)
    
    # Add git log pane
    git_log = git_window.split(direction=PaneDirection.Right)
    git_log.send_keys(f"cd {project_dir}", enter=True)
    git_log.send_keys("echo 'Git log'", enter=True)
    git_log.send_keys("git log --oneline --graph --all -n 10", enter=True)

    # Setup run window
    run_pane = run_window.active_pane
    run_pane.send_keys(f"cd {project_dir}", enter=True)
    run_pane.send_keys("echo 'Starting application...'", enter=True)
    
    # Add app logs pane
    logs_pane = run_window.split(direction=PaneDirection.Below)
    logs_pane.send_keys(f"cd {project_dir}", enter=True)
    logs_pane.send_keys("echo 'Application logs will appear here'", enter=True)

    # Return to code window
    session.select_window("code")
    
    return session, code_window, test_window, git_window, run_window

# Example usage
if __name__ == "__main__":
    project_name = "webapp-project"
    project_dir = os.path.expanduser(f"~/projects/{project_name}")
    
    # Ensure project directory exists
    os.makedirs(project_dir, exist_ok=True)
    
    session, code_window, test_window, git_window, run_window = setup_dev_environment(project_name, project_dir)
    print(f"Development environment set up in session: {session.session_name}")
    print(f"Windows created: {[w.window_name for w in session.windows]}")
```

## Data Science Workflows

Create a comprehensive data science environment:

```python
import libtmux
from libtmux.constants import PaneDirection
import os

# Connect to the tmux server
server = libtmux.Server()

def setup_data_science_env(project_name="data-science", data_dir=None):
    """Create a comprehensive data science environment"""
    if data_dir is None:
        data_dir = os.path.expanduser(f"~/data/{project_name}")
    
    try:
        session = server.new_session(session_name=project_name)
    except libtmux.exc.TmuxSessionExists:
        session = server.sessions.get(session_name=project_name)
        # Clean up existing windows
        for window in session.windows:
            window.kill()
    
    # Create windows for different data science tasks
    jupyter_window = session.new_window(window_name="jupyter")
    data_window = session.new_window(window_name="data")
    model_window = session.new_window(window_name="model")
    viz_window = session.new_window(window_name="visualization")
    
    # Setup Jupyter notebook window
    jupyter_pane = jupyter_window.active_pane
    jupyter_pane.send_keys(f"cd {data_dir}", enter=True)
    jupyter_pane.send_keys("echo 'Starting Jupyter Notebook'", enter=True)
    jupyter_pane.send_keys("jupyter notebook", enter=True)
    
    # Setup data processing window
    data_pane = data_window.active_pane
    data_pane.send_keys(f"cd {data_dir}", enter=True)
    data_pane.send_keys("echo 'Data Processing'", enter=True)
    
    # Split for data exploration
    explore_pane = data_window.split(direction=PaneDirection.Right)
    explore_pane.send_keys(f"cd {data_dir}", enter=True)
    explore_pane.send_keys("echo 'Data Exploration'", enter=True)
    explore_pane.send_keys("python -c 'import pandas as pd; print(\"Pandas version:\", pd.__version__)'", enter=True)
    
    # Setup modeling window
    model_pane = model_window.active_pane
    model_pane.send_keys(f"cd {data_dir}", enter=True)
    model_pane.send_keys("echo 'Model Training'", enter=True)
    
    # Split for model evaluation
    eval_pane = model_window.split(direction=PaneDirection.Right)
    eval_pane.send_keys(f"cd {data_dir}", enter=True)
    eval_pane.send_keys("echo 'Model Evaluation'", enter=True)
    
    # Split for hyperparameter tuning
    tune_pane = model_pane.split(direction=PaneDirection.Below)
    tune_pane.send_keys(f"cd {data_dir}", enter=True)
    tune_pane.send_keys("echo 'Hyperparameter Tuning'", enter=True)
    
    # Setup visualization window
    viz_pane = viz_window.active_pane
    viz_pane.send_keys(f"cd {data_dir}", enter=True)
    viz_pane.send_keys("echo 'Data Visualization'", enter=True)
    
    # Split for interactive dashboards
    dash_pane = viz_window.split(direction=PaneDirection.Below)
    dash_pane.send_keys(f"cd {data_dir}", enter=True)
    dash_pane.send_keys("echo 'Interactive Dashboards'", enter=True)
    
    # Return to Jupyter window
    session.select_window("jupyter")
    
    return session

# Example usage
if __name__ == "__main__":
    # Ensure data directory exists
    data_dir = os.path.expanduser("~/data/analysis-project")
    os.makedirs(data_dir, exist_ok=True)
    
    session = setup_data_science_env("analysis-project", data_dir)
    print(f"Data science environment set up in session: {session.session_name}")
    print(f"Windows: {[w.window_name for w in session.windows]}")
```
