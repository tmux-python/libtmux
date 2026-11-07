#!/usr/bin/env bash
# Print an MCP client configuration for this stack.
#
# The image ships its own at /etc/lgtm/mcp.json, but it assumes the default
# ports. This stack moves Grafana off 3000 so it does not collide with whatever
# else is running, which makes the shipped config point somewhere with nothing
# behind it -- an agent would connect, get no data, and report that the stack is
# empty rather than that it is misconfigured.
#
# The Grafana service account token is read from the running container each
# time. It is never written into the repository.
set -euo pipefail

CONTAINER="${LIBTMUX_LGTM_CONTAINER:-libtmux-lgtm}"
GRAFANA_PORT="${LIBTMUX_LGTM_GRAFANA_PORT:-3900}"

if ! docker inspect "$CONTAINER" > /dev/null 2>&1; then
	echo "the stack is not running; start it with:  just otel-up" >&2
	exit 1
fi

token="$(
	docker exec "$CONTAINER" cat /etc/lgtm/mcp.json 2> /dev/null \
		| sed -n 's/.*"GRAFANA_SERVICE_ACCOUNT_TOKEN": *"\([^"]*\)".*/\1/p'
)"
if [[ -z "$token" ]]; then
	echo "no Grafana service account token found in $CONTAINER" >&2
	exit 1
fi

cat <<EOF
{
  "mcpServers": {
    "grafana": {
      "command": "uvx",
      "args": ["mcp-grafana"],
      "env": {
        "GRAFANA_URL": "http://127.0.0.1:${GRAFANA_PORT}",
        "GRAFANA_SERVICE_ACCOUNT_TOKEN": "${token}"
      }
    },
    "tempo": {
      "type": "http",
      "url": "http://127.0.0.1:3200/api/mcp"
    }
  }
}
EOF
