#!/bin/bash
# Live origin-only on FROZEN c9v5: grants OFF (no L1/L2/L4), everything else = A (handles, floor,
# taxonomy, limits, same config_m1_c9v5, same 96 tasks, 3 passes, CaMeL, benign, governed, same
# harness/protocol/model as A). Separate ledger + dir; hard spend cap $7. Serial.
#
# DIFF vs run_c9v5.sh (config A):  (config yaml UNCHANGED — same config_m1_c9v5/<suite>.yaml)
#   - AXOR_BENCH_GRANT_LEVELS=L1        -> ""      (no L1/L2/L4 grants)
#   - drop AXOR_AJAR_GRANT_ARGS_FROM_CONFIG=1 and AXOR_AJAR_L2=tuple   (no grant args / L2 tuples)
#   - AXOR_BENCH_SPEND_CAP=12           -> 7
#   - ledger/dir  live_c9v5 -> live_origin_c9v5
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$HERE/../results/live_origin_c9v5
SPEND=$ROOT/spend.jsonl
mkdir -p $ROOT
cd /home/user/core-m1/examples/agentdojo
for PASS in 1 2 3; do
  for SUITE in banking slack travel workspace; do
    OUT=$ROOT/pass${PASS}
    mkdir -p $OUT
    env AXOR_BENCH_BACKEND=openrouter AXOR_BENCH_MODEL=openai/o4-mini AXOR_BENCH_MAXTOK=4096 \
        AXOR_BENCH_SUITE=$SUITE \
        AXOR_BENCH_CONFIG=$HERE/../config_m1_c9v5/$SUITE.yaml \
        AXOR_BENCH_CAMEL=1 AXOR_BENCH_BENIGN_ONLY=1 AXOR_BENCH_CONDITION=governed \
        AXOR_BENCH_GRANT_LEVELS= AXOR_BENCH_L4_CONFIRM=oracle \
        AXOR_AJAR_SECRETS=paper \
        AXOR_BENCH_SPEND_LOG=$SPEND AXOR_BENCH_SPEND_CAP=7 \
        AXOR_BENCH_TRAJ_DIR=$OUT/traj \
        uv run -q --no-project --with agentdojo==0.1.35 --with pyyaml --with-editable /home/user/core-m1 \
        python run_agentdojo.py > $OUT/${SUITE}.log 2>&1
    echo "== origin pass$PASS $SUITE rc=$? spend=$(python3 -c "import json;print(round(sum(json.loads(l).get('cost') or 0 for l in open('$SPEND')),4))" 2>/dev/null) $(date -u +%T)"
  done
done
touch $ROOT/ALL_DONE
echo DONE
