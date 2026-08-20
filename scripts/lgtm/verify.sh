#!/usr/bin/env bash
# Confirm each published port reaches the container's own service.
#
# A published port that answers is not proof it is yours. If a host process is
# already bound to it, Docker still publishes, but the host's process answers
# first -- so a query succeeds against the wrong backend and returns plausible
# data. That costs far more debugging time than a refused connection, because
# nothing looks broken.
#
# Liveness cannot detect it; identity can. Each service reports its own build
# info, so comparing that from inside the container against the same URL from
# the host tells the two apart.
set -uo pipefail

CONTAINER="${LIBTMUX_LGTM_CONTAINER:-libtmux-lgtm}"
GRAFANA_PORT="${LIBTMUX_LGTM_GRAFANA_PORT:-3900}"
PROM_PORT="${LIBTMUX_LGTM_PROM_PORT:-9099}"
status=0

port_variable() {
	# Only the two services this stack moves are overridable; the rest keep
	# their upstream defaults, so naming a variable for them would mislead.
	case "$1" in
		grafana) printf 'LIBTMUX_LGTM_GRAFANA_PORT' ;;
		prometheus) printf 'LIBTMUX_LGTM_PROM_PORT' ;;
		*) printf 'LIBTMUX_LGTM_CONTAINER' ;;
	esac
}

# Seconds to keep waiting for a port that is not answering yet. A service can
# still be binding when its container reports healthy, so a single sample
# turns a cold start into a spurious failure. Shadowing is not retried: two
# different services answering is a settled fact, not a timing question.
WAIT_SECONDS="${LIBTMUX_LGTM_WAIT:-30}"

check() {
	local label=$1 inside_port=$2 host_port=$3 path=$4
	local inside outside deadline
	deadline=$((SECONDS + WAIT_SECONDS))
	while :; do
		inside=$(docker exec "$CONTAINER" curl -s -m 8 "http://127.0.0.1:${inside_port}${path}" 2> /dev/null)
		outside=$(curl -s -m 8 "http://127.0.0.1:${host_port}${path}" 2> /dev/null)
		if [[ -n "$outside" && -n "$inside" ]] || ((SECONDS >= deadline)); then
			break
		fi
		sleep 2
	done
	if [[ -z "$outside" ]]; then
		printf '  %-11s %-6s UNREACHABLE from host\n' "$label" "$host_port"
		status=1
	elif [[ "$inside" == "$outside" ]]; then
		printf '  %-11s %-6s ok\n' "$label" "$host_port"
	else
		printf '  %-11s %-6s SHADOWED by another service on this port\n' "$label" "$host_port"
		printf '  %-11s %-6s   publish it elsewhere: %s=<port> just otel-up\n' \
			"" "" "$(port_variable "$label")"
		status=1
	fi
}

check grafana 3000 "$GRAFANA_PORT" /api/health
check prometheus 9090 "$PROM_PORT" /api/v1/status/buildinfo
check tempo 3200 3200 /api/status/buildinfo
check pyroscope 4040 4040 /api/v1/status/buildinfo
check loki 3100 3100 /loki/api/v1/status/buildinfo

otlp=$(curl -s -o /dev/null -m 8 -w '%{http_code}' -X POST http://127.0.0.1:4318/v1/traces 2> /dev/null)
case "$otlp" in
	2* | 4*) printf '  %-11s %-6s ok\n' otlp-http 4318 ;;
	*)
		printf '  %-11s %-6s UNREACHABLE (%s)\n' otlp-http 4318 "$otlp"
		status=1
		;;
esac

exit $status
