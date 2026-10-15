#!/bin/bash
# Paid live run on FROZEN c9v5: A (L1, no human) + B (L1+L4, view-aware confirmer), 3 passes, 4 suites,
# benign, CaMeL mode. Hard spend cap $12 across all processes via the shared ledger; references /
# description grants / per-episode logging / resume are the 83dee51 live harness. Serial so the cap
# overshoot is at most one call. slack user_task_4 is excluded in analysis (as in live_v4).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$HERE/../results/live_c9v5
SPEND=$ROOT/spend.jsonl
mkdir -p $ROOT
cd /home/user/core-m1/examples/agentdojo
for PASS in 1 2 3; do
  for CFG in A B; do
    case $CFG in A) LEVELS=L1; CONF=oracle ;; B) LEVELS=L1+L4; CONF=view ;; esac
    for SUITE in banking slack travel workspace; do
      OUT=$ROOT/${CFG}/pass${PASS}
      mkdir -p $OUT
      env AXOR_BENCH_BACKEND=openrouter AXOR_BENCH_MODEL=openai/o4-mini AXOR_BENCH_MAXTOK=4096 \
          AXOR_BENCH_SUITE=$SUITE \
          AXOR_BENCH_CONFIG=$HERE/../config_m1_c9v5/$SUITE.yaml \
          AXOR_BENCH_CAMEL=1 AXOR_BENCH_BENIGN_ONLY=1 AXOR_BENCH_CONDITION=governed \
          AXOR_BENCH_GRANT_LEVELS=$LEVELS AXOR_BENCH_L4_BUDGET=5 AXOR_BENCH_L4_CONFIRM=$CONF \
          AXOR_AJAR_SECRETS=paper AXOR_AJAR_GRANT_ARGS_FROM_CONFIG=1 AXOR_AJAR_L2=tuple \
          AXOR_BENCH_SPEND_LOG=$SPEND AXOR_BENCH_SPEND_CAP=12 \
          AXOR_BENCH_TRAJ_DIR=$OUT/traj \
          uv run -q --no-project --with agentdojo==0.1.35 --with pyyaml --with-editable /home/user/core-m1 \
          python run_agentdojo.py > $OUT/${SUITE}.log 2>&1
      echo "== $CFG pass$PASS $SUITE rc=$? spend=$(python3 -c "import json;print(round(sum(json.loads(l).get('cost') or 0 for l in open('$SPEND')),4))" 2>/dev/null) $(date -u +%T)"
    done
  done
done
touch $ROOT/ALL_DONE
echo DONE
