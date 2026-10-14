#!/bin/bash
# $1 = A|B  $2 = pass  $3 = comma-separated user tasks (workspace)
set -u
CFG=$1; PASS=$2; TASKS=$3
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$HERE/../results/live_final/rerun814/${CFG}/pass${PASS}
mkdir -p $OUT
case $CFG in A) LEVELS=L1 ;; B) LEVELS=L1+L4 ;; *) exit 2 ;; esac
cd /home/user/core-m1/examples/agentdojo
env AXOR_BENCH_BACKEND=openrouter AXOR_BENCH_MODEL=openai/o4-mini AXOR_BENCH_MAXTOK=4096 \
    AXOR_BENCH_SUITE=workspace AXOR_BENCH_CONFIG=$HERE/../config_m1_c814/workspace.yaml \
    AXOR_BENCH_CAMEL=1 AXOR_BENCH_BENIGN_ONLY=1 AXOR_BENCH_CONDITION=governed AXOR_BENCH_GRANT_LEVELS=$LEVELS \
    AXOR_BENCH_L4_BUDGET=5 AXOR_BENCH_SPEND_LOG=$HERE/../results/live_final/rerun814/spend.jsonl \
    AXOR_BENCH_SPEND_CAP=2 AXOR_BENCH_TRAJ_DIR=$OUT/traj AXOR_BENCH_USER_TASKS=$TASKS \
    uv run -q --no-project --with agentdojo==0.1.35 --with pyyaml --with-editable /home/user/core-m1 \
    python run_agentdojo.py > $OUT/workspace.log 2>&1
echo "== RUN DONE $CFG pass$PASS rc=$? $(date -u +%T)" >> $OUT/workspace.log
