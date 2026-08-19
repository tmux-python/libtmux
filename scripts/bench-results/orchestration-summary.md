# Active orchestration benchmark

> Local descriptive evidence only; these timings are not causal or machine-independent claims.

Status: `completed`

Requested topology: `80x20x1`

Observed topology: `80x20x1`

Lane: `control/async`

Runs: `100`

Warmup: `5`

Seed: `20260818`

Python: `3.14.6`

tmux: `tmux 3.7b`

Revision: `4dbbd5af77b9fc6da9664e2ace9b17ca172e6dab`

## Phase timings

| Phase | Status | Count | Min | Mean | Median | p90 | p95 | p99 | Max |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `setup` | `completed` | 1 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| `stabilization` | `completed` | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| `mutation.bulk` | `completed` | 100 | 9.015 ms | 35.725 ms | 22.409 ms | 66.378 ms | 128.700 ms | 186.153 ms | 209.701 ms |
| `wait.capture-poll` | `completed` | 100 | 4.424 ms | 14.683 ms | 14.702 ms | 21.885 ms | 23.552 ms | 31.861 ms | 37.837 ms |
| `wait.control-stream` | `completed` | 100 | 2.570 ms | 4.972 ms | 4.743 ms | 7.297 ms | 8.915 ms | 9.775 ms | 10.447 ms |
| `enumeration.sessions` | `completed` | 100 | 41.006 ms | 62.269 ms | 59.187 ms | 83.106 ms | 88.892 ms | 117.194 ms | 138.169 ms |
| `enumeration.windows` | `completed` | 100 | 684.147 ms | 852.753 ms | 836.380 ms | 991.481 ms | 1056.152 ms | 1107.894 ms | 1158.163 ms |
| `enumeration.panes` | `completed` | 100 | 671.051 ms | 838.898 ms | 835.532 ms | 952.230 ms | 971.418 ms | 1024.236 ms | 1108.716 ms |
| `capture.serial` | `completed` | 100 | 5136.959 ms | 5733.868 ms | 5687.683 ms | 6042.626 ms | 6274.719 ms | 6545.296 ms | 7027.275 ms |
| `capture.batched` | `completed` | 100 | 702.161 ms | 857.472 ms | 837.555 ms | 997.271 ms | 1018.689 ms | 1085.141 ms | 1117.634 ms |
| `search.classic.sessions.first` | `completed` | 100 | 9.635 ms | 16.968 ms | 16.116 ms | 21.054 ms | 23.458 ms | 30.580 ms | 36.277 ms |
| `search.classic.sessions.middle` | `completed` | 100 | 9.792 ms | 16.735 ms | 15.340 ms | 22.940 ms | 26.415 ms | 31.543 ms | 38.306 ms |
| `search.classic.sessions.last` | `completed` | 100 | 9.585 ms | 16.823 ms | 16.375 ms | 21.661 ms | 24.283 ms | 32.193 ms | 32.290 ms |
| `search.classic.windows.first` | `completed` | 100 | 15.891 ms | 25.795 ms | 24.149 ms | 34.969 ms | 38.185 ms | 42.886 ms | 55.252 ms |
| `search.classic.windows.middle` | `completed` | 100 | 16.323 ms | 25.302 ms | 24.024 ms | 32.993 ms | 37.759 ms | 41.424 ms | 63.667 ms |
| `search.classic.windows.last` | `completed` | 100 | 15.785 ms | 25.803 ms | 24.156 ms | 33.562 ms | 37.517 ms | 41.283 ms | 55.281 ms |
| `search.classic.panes.first` | `completed` | 100 | 16.007 ms | 24.313 ms | 23.075 ms | 31.651 ms | 33.008 ms | 37.517 ms | 39.586 ms |
| `search.classic.panes.middle` | `completed` | 100 | 17.354 ms | 25.784 ms | 24.617 ms | 34.194 ms | 35.920 ms | 40.064 ms | 41.065 ms |
| `search.classic.panes.last` | `completed` | 100 | 16.979 ms | 25.098 ms | 23.633 ms | 31.654 ms | 35.286 ms | 39.591 ms | 43.503 ms |
| `search.snapshot.sessions.first` | `completed` | 100 | 0.105 ms | 0.120 ms | 0.111 ms | 0.137 ms | 0.153 ms | 0.266 ms | 0.292 ms |
| `search.snapshot.sessions.middle` | `completed` | 100 | 0.105 ms | 0.119 ms | 0.112 ms | 0.128 ms | 0.145 ms | 0.271 ms | 0.278 ms |
| `search.snapshot.sessions.last` | `completed` | 100 | 0.104 ms | 0.115 ms | 0.112 ms | 0.125 ms | 0.136 ms | 0.153 ms | 0.154 ms |
| `search.snapshot.windows.first` | `completed` | 100 | 1.739 ms | 1.853 ms | 1.830 ms | 1.936 ms | 2.061 ms | 2.320 ms | 2.546 ms |
| `search.snapshot.windows.middle` | `completed` | 100 | 1.675 ms | 1.837 ms | 1.812 ms | 1.926 ms | 1.941 ms | 2.383 ms | 2.506 ms |
| `search.snapshot.windows.last` | `completed` | 100 | 1.724 ms | 1.861 ms | 1.824 ms | 1.962 ms | 2.163 ms | 2.350 ms | 2.444 ms |
| `search.snapshot.panes.first` | `completed` | 100 | 1.710 ms | 1.850 ms | 1.819 ms | 1.916 ms | 2.101 ms | 2.475 ms | 3.010 ms |
| `search.snapshot.panes.middle` | `completed` | 100 | 1.645 ms | 1.835 ms | 1.807 ms | 1.881 ms | 1.961 ms | 2.456 ms | 3.350 ms |
| `search.snapshot.panes.last` | `completed` | 100 | 1.716 ms | 1.837 ms | 1.820 ms | 1.913 ms | 1.970 ms | 2.280 ms | 2.334 ms |
| `search.end-to-end.sessions.first` | `completed` | 100 | 29.435 ms | 38.449 ms | 36.652 ms | 44.327 ms | 48.375 ms | 77.009 ms | 77.385 ms |
| `search.end-to-end.sessions.middle` | `completed` | 100 | 30.575 ms | 36.560 ms | 36.055 ms | 40.444 ms | 42.816 ms | 45.671 ms | 51.883 ms |
| `search.end-to-end.sessions.last` | `completed` | 100 | 32.270 ms | 40.356 ms | 39.833 ms | 45.612 ms | 47.196 ms | 52.118 ms | 52.254 ms |
| `search.end-to-end.windows.first` | `completed` | 100 | 546.626 ms | 667.110 ms | 656.230 ms | 757.846 ms | 775.779 ms | 819.850 ms | 853.090 ms |
| `search.end-to-end.windows.middle` | `completed` | 100 | 529.188 ms | 662.963 ms | 648.651 ms | 747.818 ms | 794.568 ms | 814.376 ms | 953.211 ms |
| `search.end-to-end.windows.last` | `completed` | 100 | 530.313 ms | 660.803 ms | 659.121 ms | 732.606 ms | 759.430 ms | 802.191 ms | 852.603 ms |
| `search.end-to-end.panes.first` | `completed` | 100 | 538.844 ms | 643.985 ms | 639.942 ms | 707.542 ms | 745.389 ms | 772.805 ms | 778.258 ms |
| `search.end-to-end.panes.middle` | `completed` | 100 | 525.370 ms | 647.579 ms | 629.635 ms | 741.772 ms | 782.001 ms | 810.547 ms | 842.663 ms |
| `search.end-to-end.panes.last` | `completed` | 100 | 569.127 ms | 651.062 ms | 640.195 ms | 740.188 ms | 744.479 ms | 795.558 ms | 818.860 ms |
| `search.contents` | `completed` | 100 | 2.123 ms | 2.364 ms | 2.301 ms | 2.569 ms | 2.668 ms | 4.038 ms | 4.039 ms |

Setup individual observations: `5372.873 ms`

## Cleanup

Verified complete: `true`

Processes absent: `true`

Socket absent: `true`

Scratch absent: `true`
