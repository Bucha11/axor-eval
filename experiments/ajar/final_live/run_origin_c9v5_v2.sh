#!/bin/bash
# №2 RE-RUN from scratch. Live origin-only on FROZEN c9v5, grants genuinely OFF via the
# shared ablation flag AXOR_BENCH_NO_GRANTS=1 (strips grant_args/grant_templates/grant_quotas/
# description/delegated/list from the config, restores the default consequence ceiling —
# the SAME grant_ablation.strip_grants the Ajar harness uses for no_grants). Everything
# else = A (handles, floor, taxonomy, limits, same config_m1_c9v5/<suite>.yaml, same 96
# tasks = 4 suites x 3 passes, o4-mini, CaMeL, benign, governed, same harness/model).
#
# WHY v2: run_origin_c9v5.sh set only AXOR_BENCH_GRANT_LEVELS="" which does NOT strip the
# config's own grant machinery; that partial run (results/live_origin_c9v5_contaminated/)
# still carried L1/L2 grant_source and grant_gate denials and is discarded.
#
# DIFF vs run_origin_c9v5.sh:
#   + AXOR_BENCH_NO_GRANTS=1            (the real origin-only disable)
#   - results dir  live_origin_c9v5 -> live_origin_c9v5_v2   (fresh ledger, not mixed)
# Hard spend cap $7. Serial.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$HERE/../results/live_origin_c9v5_v2
SPEND=$ROOT/spend.jsonl
mkdir -p $ROOT
cd /home/user/core-m1/examples/agentdojo
for PASS in 1 2 3; do
  for SUITE in banking slack travel workspace; do
    OUT=$ROOT/pass${PASS}
    mkdir -p $OUT
    # resumable: skip a (pass,suite) unit already completed in an earlier background slot
    # (the run is wall-clock-limited, not budget-limited; the shared ledger enforces $7
    # cumulatively across restarts, so completed units are never re-spent).
    if [ -f "$OUT/${SUITE}.done" ]; then
      echo "== origin-v2 pass$PASS $SUITE SKIP (already done) $(date -u +%T)"; continue
    fi
    env AXOR_BENCH_BACKEND=openrouter AXOR_BENCH_MODEL=openai/o4-mini AXOR_BENCH_MAXTOK=4096 \
        AXOR_BENCH_SUITE=$SUITE \
        AXOR_BENCH_CONFIG=$HERE/../config_m1_c9v5/$SUITE.yaml \
        AXOR_BENCH_CAMEL=1 AXOR_BENCH_BENIGN_ONLY=1 AXOR_BENCH_CONDITION=governed \
        AXOR_BENCH_GRANT_LEVELS= AXOR_BENCH_NO_GRANTS=1 AXOR_BENCH_L4_CONFIRM=oracle \
        AXOR_AJAR_SECRETS=paper \
        AXOR_BENCH_SPEND_LOG=$SPEND AXOR_BENCH_SPEND_CAP=7 \
        AXOR_BENCH_TRAJ_DIR=$OUT/traj \
        uv run -q --no-project --with agentdojo==0.1.35 --with pyyaml --with-editable /home/user/core-m1 \
        python run_agentdojo.py > $OUT/${SUITE}.log 2>&1
    RC=$?
    [ $RC -eq 0 ] && touch "$OUT/${SUITE}.done"
    echo "== origin-v2 pass$PASS $SUITE rc=$RC spend=$(python3 -c "import json;print(round(sum(json.loads(l).get('cost') or 0 for l in open('$SPEND')),4))" 2>/dev/null) $(date -u +%T)"
  done
done
touch $ROOT/ALL_DONE
echo DONE
