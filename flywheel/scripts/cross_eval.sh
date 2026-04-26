#!/usr/bin/env bash
# Run the 4 handtuned-arc prompts on a different video to test generalization.
# Usage: bash flywheel/scripts/cross_eval.sh <game_name>
#   e.g. bash flywheel/scripts/cross_eval.sh chris-instructor

set -euo pipefail
cd "$(dirname "$0")/../.."

# Resolve python: prefer venv if present
PY="${PY:-$(pwd)/.venv/bin/python}"
if [ ! -x "${PY}" ]; then PY="$(command -v python3 || command -v python)"; fi
echo "Using python: ${PY}"

GAME="${1:-chris-instructor}"
VIDEO="VLM-gemini/input-data/${GAME}/video.mov"
GT="VLM-gemini/input-data/${GAME}/subs.json"
OUT_BASE="flywheel/outputs/cross_eval/${GAME}"

if [ ! -f "${VIDEO}" ]; then echo "missing ${VIDEO}" >&2; exit 1; fi
if [ ! -f "${GT}" ];    then echo "missing ${GT}"    >&2; exit 1; fi

# Handtuned arc, in order
declare -a PROMPTS=(
  "v1:pv-ac5575b2-da74-46ed-93c0-af646accf89b"
  "v2:pv-b535d177-bf2c-4659-a784-75ee44ab6fd8"
  "v3:pv-853f6c04-aee7-4b70-964e-7db81f69da6a"
  "v4:pv-377be9c6-d965-4e43-9511-43ab10ecd725"
)

mkdir -p "${OUT_BASE}"
echo "Cross-eval ${GAME}: 4 prompts × 1 video"
echo

for entry in "${PROMPTS[@]}"; do
  LABEL="${entry%%:*}"
  PV="${entry##*:}"
  RULES="flywheel/outputs/runs/verify:video/${PV}/domain_rules.md"
  OUT_DIR="${OUT_BASE}/${LABEL}-${PV:0:11}"

  if [ ! -f "${RULES}" ]; then echo "  ${LABEL}: missing ${RULES}" >&2; continue; fi

  echo "=========================================================="
  echo "[$(date -u +%H:%M:%S)]  ${LABEL}  (${PV:0:11})"
  echo "=========================================================="

  "${PY}" VLM-gemini/analyze.py "${VIDEO}" \
    --out-dir "${OUT_DIR}" \
    --domain-rules "${RULES}" \
    --model gemini-3-flash-preview \
    --workers 12 2>&1 | tail -30

  echo
  echo "  Eval:"
  ( cd VLM-gemini && "${PY}" -m eval.run_eval \
      --pred "../${OUT_DIR}/result.json" \
      --gt "../${GT}" \
      --config "${GAME}:${LABEL}" \
      --tau 10 ) | tail -20

  echo
done

echo "=========================================================="
echo "DONE — outputs in ${OUT_BASE}"
ls -1 "${OUT_BASE}"
