#!/bin/sh
set -eu
exec ssh -T -F "${VIBECODING_EXECUTOR_SSH_CONFIG:?}" vibecoding-host "$@"
