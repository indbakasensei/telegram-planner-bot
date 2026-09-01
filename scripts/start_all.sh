#!/usr/bin/env bash
# scripts/start_all.sh

cd "$(dirname "$0")" || exit 1

./start_planner.sh
./start_qa.sh

sleep 2
./status.sh
