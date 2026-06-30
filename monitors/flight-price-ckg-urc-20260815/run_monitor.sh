#!/usr/bin/env bash
set -euo pipefail

cd /home/admin/ai/monitors/flight-price-ckg-urc-20260815
set -a
source ./env
set +a

exec /usr/bin/python3 ./monitor.py
