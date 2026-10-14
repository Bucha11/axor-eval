#!/bin/bash
# One governed benign pass of one suite. $1 = A|B, $2 = pass, $3 = suite, [$4 = task slice a:b]
set -u
CFG=$1; PASS=$2; SUITE=$3; SLICE=${4:-}
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$HERE/../results/live_final/${CFG}/pass${PASS}
[ -n "$SLICE" ] && OUT=$HERE/../results/live_final/smoke/${CFG}
mkdir -p $OUT
case $CFG in A) LEVELS=L1 ;; B) LEVELS=L1+L4 ;; *) echo "A|B"; exit 2 ;; esac
cd /home/user/core-m1/examples/agentdojo
env AXOR_BENCH_BACKEND=openrouter AXOR_BENCH_MODEL=openai/o4-mini AXOR_BENCH_MAXTOK=4096 \
    AXOR_BENCH_SUITE=$SUITE AXOR_BENCH_CONFIG=$HERE/../config_m1_content/$SUITE.yaml \
    AXOR_BENCH_BENIGN_ONLY=1 AXOR_BENCH_CONDITION=governed AXOR_BENCH_GRANT_LEVELS=$LEVELS \
    AXOR_BENCH_L4_BUDGET=5 AXOR_BENCH_SPEND_LOG=$HERE/../results/live_final/spend.jsonl \
    AXOR_BENCH_SPEND_CAP=12 AXOR_BENCH_TRAJ_DIR=$OUT/traj \
    ${SLICE:+AXOR_BENCH_TASK_SLICE=$SLICE} \
    uv run -q --no-project --with agentdojo==0.1.35 --with pyyaml --with-editable /home/user/core-m1 \
    python run_agentdojo.py > $OUT/${SUITE}${SLICE:+_$SLICE}.log 2>&1
echo "== RUN DONE $CFG pass$PASS $SUITE rc=$? $(date -u +%T)" >> $OUT/${SUITE}${SLICE:+_$SLICE}.log
