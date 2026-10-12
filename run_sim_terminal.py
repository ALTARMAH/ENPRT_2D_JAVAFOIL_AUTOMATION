#!/usr/bin/env python3
"""Run a single simulation in a terminal. Reads config from JSON file."""
import os, sys, json

# Setup worker directory
from queue import Queue
import aero_auto as A
w = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workers")
A.WORKER_DIRS = Queue()
A.WORKER_DIRS.put(w)

# Load airfoils
A.AIRFOILS.update(A.load_all(A.AIRFOIL_DIR))
A.load_store()

def main():
    if len(sys.argv) < 2:
        print("Usage: run_sim_terminal.py <config.json>")
        sys.exit(1)
    
    config_file = sys.argv[1]
    try:
        with open(config_file) as f:
            config = json.load(f)
    except (OSError, ValueError) as e:
        print(f"cannot read config {config_file}: {e}")
        sys.exit(1)

    missing = [k for k in ("main", "flaps", "re", "speed", "chord", "role") if k not in config]
    if missing:
        print(f"config is missing required key(s): {', '.join(missing)}")
        sys.exit(1)

    cfg = (config['main'], tuple(config['flaps']))
    A.RE = config['re']
    A.SPEED = config['speed']
    A.CHORD_MM = config['chord']
    A.ROLE = config['role']
    A.REG = A.default_reg()
    A.REG_ENFORCE = config.get('reg_enforce', True)
    A.GROUND_H = config.get('ground_h')
    A.RESULTS_FILE[0] = config.get('results_file', os.path.join(A.OUT_DIR, 'results.csv'))
    os.makedirs(os.path.dirname(os.path.abspath(A.RESULTS_FILE[0])), exist_ok=True)
    
    print(f"Simulating {config['main']} + {len(config['flaps'])} flaps...")
    row = A.run_one(cfg, "ui", config.get('ground_h'))
    
    def f(k, spec=""):
        v = row.get(k)
        return ("--" if v is None else format(v, spec)) if spec else ("--" if v is None else str(v))
    
    print(f"Result: {row.get('Run_ID')} {row.get('Status')}")
    print(f"  Cl@0 {f('Cl_a0','.3f')}  Cd@0 {f('Cd_a0','.4f')}  max|L/D| {f('Max_LD','.1f')}  stall {row.get('Stall_Angle')} deg")
    print(f"  downforce {f('Downforce_N','.0f')} N")
    print(f"Results saved to {A.RESULTS_FILE[0]}")

if __name__ == '__main__':
    main()
