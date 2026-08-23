# Engine tutorials

Each concrete engine has one tested workflow:

| Engine | Tutorial outcome |
| --- | --- |
| `SubprocessEngine` | {doc}`live-operation` returns a typed result from an isolated live server. |
| `AsyncSubprocessEngine` | {doc}`async-subprocess` runs two independent live reads concurrently. |
| `ControlModeEngine` | {doc}`control-mode` pipelines an ordered request batch over one synchronous connection. |
| `AsyncControlModeEngine` | {doc}`async-control-plans` resolves a forward reference and verifies the live pane in two planner steps. |
| `MockEngine` and `AsyncMockEngine` | {doc}`offline-testing` distinguishes canned output and fabricated IDs from live tmux state. |
| `ImsgEngine` | {doc}`imsg-parity` compares one live stdout value with the subprocess transport. |

{doc}`results-and-failures` is the shared guide to typed success, command
failure, expected absence, and version rejection.

```{toctree}
:hidden:

live-operation
results-and-failures
async-control-plans
async-subprocess
control-mode
offline-testing
imsg-parity
```
