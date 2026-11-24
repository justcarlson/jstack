#!/bin/sh
# Thin wrapper: install jstack skills. See scripts/install.py --help.
set -eu
here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$here/scripts/install.py" "$@"
