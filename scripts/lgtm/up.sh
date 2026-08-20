#!/usr/bin/env bash
# Start the local Grafana LGTM stack that the telemetry checks query against.
#
# One container runs Grafana, Loki, Tempo, Prometheus, Pyroscope, and an
# OpenTelemetry collector in front of them. The libtmux dashboards are
# regenerated and bind-mounted on every start, so a fresh checkout gets the
# same boards without clicking through the UI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONTAINER="${LIBTMUX_LGTM_CONTAINER:-libtmux-lgtm}"

# Pin the image rather than tracking :latest, so a rerun months from now sees
# the Prometheus and Pyroscope this stack was verified against. 0.30.2 runs
# Prometheus 3.13 with --web.enable-otlp-receiver and
# --enable-feature=exemplar-storage, which is what makes the metric-to-trace
# pivot in the dashboards work.
IMAGE="${LIBTMUX_LGTM_IMAGE:-docker.io/grafana/otel-lgtm:0.30.2}"

# Grafana's own default is 3000 and Prometheus's is 9090. Both are commonly
# taken on a dev box, and a taken port does not fail loudly: Docker still
# publishes, but a host process already bound there answers first, so queries
# reach the WRONG server and return plausible data. verify.sh checks for
# exactly that. Override either if these also collide.
GRAFANA_PORT="${LIBTMUX_LGTM_GRAFANA_PORT:-3900}"
PROM_PORT="${LIBTMUX_LGTM_PROM_PORT:-9099}"

# Bump when the mounted config or the run shape changes, so an existing
# container is recreated rather than restarted with stale mounts.
CONFIG_LABEL="dashboards-v2-mcp"

if [[ -n "${PYTHON:-}" ]]; then
	read -r -a python_cmd <<< "$PYTHON"
elif command -v uv > /dev/null 2>&1 && [[ -f "$ROOT/pyproject.toml" ]]; then
	python_cmd=(uv run python)
else
	python_cmd=(python3)
fi

"${python_cmd[@]}" "$ROOT/scripts/lgtm/generate_dashboards.py" \
	--output "$ROOT/scripts/lgtm/dashboards"

docker_run=(
	run
	-d
	--name "$CONTAINER"
	--init
	--restart unless-stopped
	--label "libtmux.lgtm.config=$CONFIG_LABEL"
	-p "${GRAFANA_PORT}:3000"
	-p 3100:3100
	-p 3200:3200
	-p 4040:4040
	-p 4317:4317
	-p 4318:4318
	-p "${PROM_PORT}:9090"
	-v "$ROOT/scripts/lgtm/grafana-datasources.yaml:/otel-lgtm/grafana/conf/provisioning/datasources/grafana-datasources.yaml:ro"
	-v "$ROOT/scripts/lgtm/grafana-dashboards-libtmux.yaml:/otel-lgtm/grafana/conf/provisioning/dashboards/libtmux.yaml:ro"
	-v "$ROOT/scripts/lgtm/dashboards:/otel-lgtm/dashboards-libtmux:ro"
	-e GF_PATHS_DATA=/data/grafana
	# Tempo's MCP server is off by default. Turning it on costs nothing when
	# unused and is what lets an agent query traces directly rather than being
	# handed screenshots of them.
	-e TEMPO_EXTRA_ARGS=--query-frontend.mcp-server.enabled=true
	"$IMAGE"
)

if docker inspect "$CONTAINER" > /dev/null 2>&1; then
	current="$(
		docker inspect --format '{{ index .Config.Labels "libtmux.lgtm.config" }}' \
			"$CONTAINER" 2> /dev/null || true
	)"
	if [[ "$current" != "$CONFIG_LABEL" ]]; then
		docker rm -f "$CONTAINER" > /dev/null
		docker "${docker_run[@]}" > /dev/null
	else
		docker start "$CONTAINER" > /dev/null
	fi
else
	docker "${docker_run[@]}" > /dev/null
fi

printf 'waiting for the stack'
for _ in $(seq 1 45); do
	state="$(docker inspect --format '{{.State.Health.Status}}' "$CONTAINER" 2> /dev/null || echo none)"
	if [[ "$state" == "healthy" ]]; then
		printf '\n'
		break
	fi
	printf '.'
	sleep 4
done

# Identity, not liveness: a port that answers may belong to a host process
# that was already bound to it. verify.sh tells the two apart.
"$ROOT/scripts/lgtm/verify.sh" || {
	echo "a published port does not reach this container; see the lines above," >&2
	echo "then republish on a free port, for example:" >&2
	echo "  LIBTMUX_LGTM_PROM_PORT=9098 just otel-up" >&2
	exit 1
}

cat <<EOF
grafana    http://127.0.0.1:${GRAFANA_PORT}  (admin/admin)
prometheus http://127.0.0.1:${PROM_PORT}
tempo      http://127.0.0.1:3200
pyroscope  http://127.0.0.1:4040
loki       http://127.0.0.1:3100
otlp       grpc 4317 / http 4318
EOF
