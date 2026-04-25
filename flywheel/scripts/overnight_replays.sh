#!/usr/bin/env bash
# Overnight replay sweep — for each (seed, replay_idx) combination,
# provision a fresh MuBit agent and run a full N-iteration loop.
# All loop_arc.json files are preserved in flywheel/outputs/sweep/.
#
# Usage (from repo root):
#   bash flywheel/scripts/overnight_replays.sh
#
# Env knobs:
#   N_REPLAYS    how many replay arcs per seed (default 3)
#   ITERATIONS   loop iterations per arc (default 6)
#   SEEDS        space-separated "promptfile:label" pairs
#                  default: "verifier_naive.md:naive verifier_v1.md:handtuned"
#
# Total runtime estimate: N_REPLAYS * len(SEEDS) * ITERATIONS * ~2.5min
#   defaults => 3 * 2 * 6 * 2.5 ≈ 90 min

set -euo pipefail

cd "$(dirname "$0")/../.."
REPO_ROOT="$(pwd)"
echo "Repo root: ${REPO_ROOT}"

N_REPLAYS="${N_REPLAYS:-3}"
ITERATIONS="${ITERATIONS:-6}"
SEEDS="${SEEDS:-verifier_naive.md:naive verifier_v1.md:handtuned}"

SWEEP_DIR="${REPO_ROOT}/flywheel/outputs/sweep"
LOG_DIR="${SWEEP_DIR}/logs"
mkdir -p "${SWEEP_DIR}" "${LOG_DIR}"

STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Sweep started at ${STARTED_AT}"
echo "  N_REPLAYS  = ${N_REPLAYS}"
echo "  ITERATIONS = ${ITERATIONS}"
echo "  SEEDS      = ${SEEDS}"
echo

for seed_pair in ${SEEDS}; do
  prompt="${seed_pair%%:*}"
  label="${seed_pair##*:}"
  for i in $(seq 1 "${N_REPLAYS}"); do
    AGENT="submission-detector-${label}-r${i}"
    LOG="${LOG_DIR}/${label}_r${i}.log"
    ARC_OUT="${SWEEP_DIR}/loop_arc_${label}_r${i}.json"

    echo "================================================================"
    echo "[$(date -u +%H:%M:%S)] ${label} replay ${i}/${N_REPLAYS}"
    echo "  prompt = ${prompt}"
    echo "  agent  = ${AGENT}"
    echo "  log    = ${LOG}"
    echo "================================================================"

    export FLYWHEEL_SEED_PROMPT="${prompt}"
    export FLYWHEEL_AGENT_ID="${AGENT}"

    # Provision fresh agent (idempotent — re-running just confirms exists).
    python -m flywheel.cli setup >>"${LOG}" 2>&1 || {
      echo "  setup failed; see ${LOG}" >&2
      continue
    }

    # Run the loop.
    python -u -m flywheel.cli loop --iterations "${ITERATIONS}" \
      >>"${LOG}" 2>&1 || {
      echo "  loop failed; see ${LOG}" >&2
      continue
    }

    # Snapshot loop_arc.json so the next run doesn't overwrite.
    if [ -f "${REPO_ROOT}/flywheel/outputs/loop_arc.json" ]; then
      cp "${REPO_ROOT}/flywheel/outputs/loop_arc.json" "${ARC_OUT}"
      echo "  saved arc → ${ARC_OUT}"
    fi
  done
done

ENDED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo
echo "================================================================"
echo "Sweep complete. Started ${STARTED_AT}, ended ${ENDED_AT}"
echo "Arcs saved to: ${SWEEP_DIR}"
ls -1 "${SWEEP_DIR}"/loop_arc_*.json 2>/dev/null || echo "  (no arcs produced)"
echo "================================================================"
