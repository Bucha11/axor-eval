#!/bin/bash
# Stop every run when errored tasks exceed 5% of finished tasks (after >= 20 finished).
ROOT=$(cd "$(dirname "$0")" && pwd)/../results/live_final
while sleep 30; do
  done_=$(grep -rhoE "\[GOVERNED ?\] +user_task_[0-9]+ +\(benign\)" $ROOT --include=*.log 2>/dev/null | wc -l)
  err=$(grep -rE "\[GOVERNED ?\] +user_task_[0-9]+: ERROR" $ROOT --include=*.log 2>/dev/null | grep -vE "/slack[^/:]*\.log:.*user_task_4:" | wc -l)
  tot=$((done_ + err))
  if [ $tot -ge 20 ] && [ $((err * 100)) -gt $((tot * 5)) ]; then
    echo "STOPPED $(date -u +%T): $err errors of $tot tasks" > $ROOT/STOPPED
    pkill -f "run_agentdojo.py"; exit 1
  fi
  [ -f $ROOT/ALL_DONE ] && exit 0
done
