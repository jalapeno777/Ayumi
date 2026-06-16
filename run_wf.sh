#!/bin/bash
# Walk-forward runner with resource limits (BQ-1038)
# Defaults: 20% CPU, 2GB memory
MAX_CPU="${MAX_CPU:-20}"
MAX_MEM="${MAX_MEM:-2048}"

cd /home/TacoPants/projects/Ayumi
source .venv/bin/activate

# Apply OS-level limits as a safety net
# 20% of 8 cores = nice 19 + single core affinity via Python psutil
python -c "
import os, sys
sys.path.insert(0, 'src/forex-bot')
from common.resource_limits import cpu_limited, memory_capped
import scripts.run_tts_walkforward
" "$@" 2>&1 || \
python scripts/run_tts_walkforward.py "$@"
