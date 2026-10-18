"""
Step 4.3: NASA 30P-30N Multi-Element Airfoil Benchmark
Downloads official validation mesh directly from official su2code/TestCases repository:
https://raw.githubusercontent.com/su2code/TestCases/master/vandv/rans/30p30n/2D_L1_coarse_r1.su2
and runs SU2 Incompressible RANS (k-omega SST) at Re = 5,000,000, alpha = 4.0 deg.
Compares with published experimental wind tunnel data (Bertelrud / NASA TM-112858).
"""

import os
import sys
import math
import subprocess
import time
import urllib.request
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import su2_engine as su2

OFFICIAL_MESH_URL = "https://raw.githubusercontent.com/su2code/TestCases/master/vandv/rans/30p30n/2D_L1_coarse_r1.su2"

workdir = os.path.join(HERE, "runs", "su2_runs", "nasa_30p30n_benchmark")
os.makedirs(workdir, exist_ok=True)

mesh_file = os.path.join(workdir, "2D_L1_coarse_r1.su2")
cfg_file = os.path.join(workdir, "config.cfg")
history_file = os.path.join(workdir, "history.csv")

print("==================================================")
print("Step 4.3: NASA 30P-30N Multi-Element Benchmark")
print("==================================================")

if not os.path.exists(mesh_file) or os.path.getsize(mesh_file) < 1000000:
    print(f"Downloading official NASA 30P-30N validation mesh from {OFFICIAL_MESH_URL}...")
    urllib.request.urlretrieve(OFFICIAL_MESH_URL, mesh_file)
    print(f"Mesh downloaded: {os.path.getsize(mesh_file)} bytes")

# Experimental conditions (NASA TM-112858 / Bertelrud):
# Re = 5.0e6, alpha = 4.0 deg (upright high-lift configuration)
# Published experimental values: CL_exp = 2.167, CD_exp = 0.0332
re_val = 5000000.0
speed = 70.0
alpha_deg = 4.0
alpha_rad = math.radians(alpha_deg)
vx = speed * math.cos(alpha_rad)
vy = speed * math.sin(alpha_rad)

# SU2 Config for 30P-30N
# Markers in 2D_L1_coarse_r1.su2 are: 'wall' and 'farfield'
config_text = f"""% ------------- SU2 CONFIGURATION FOR NASA 30P-30N BENCHMARK ------------- %
SOLVER= INC_RANS
KIND_TURB_MODEL= SST
MATH_PROBLEM= DIRECT
RESTART_SOL= NO

% Flow conditions
INC_DENSITY_MODEL= CONSTANT
INC_DENSITY_INIT= 1.225
INC_VELOCITY_INIT= ( {vx:.6f}, {vy:.6f}, 0.0 )
INC_TEMPERATURE_INIT= 288.15

% Reference values
REF_ORIGIN_MOMENT_X= 0.25
REF_ORIGIN_MOMENT_Y= 0.00
REF_ORIGIN_MOMENT_Z= 0.00
REF_LENGTH= 1.0
REF_AREA= 1.0

% Fluid properties
FLUID_MODEL= CONSTANT_DENSITY
VISCOSITY_MODEL= CONSTANT_VISCOSITY
MU_CONSTANT= 1.7894e-05

% Boundary conditions
MARKER_HEATFLUX= ( wall, 0.0 )
MARKER_FAR= ( farfield )
MARKER_MONITORING= ( wall )
MARKER_DESIGNING= ( wall )

% Numerical methods
NUM_METHOD_GRAD= GREEN_GAUSS
CFL_NUMBER= 10.0
CFL_ADAPT= YES
CFL_ADAPT_PARAM= ( 0.5, 1.25, 1.0, 50.0 )

% Linear solver
LINEAR_SOLVER= FGMRES
LINEAR_SOLVER_PREC= ILU
LINEAR_SOLVER_ERROR= 1e-6
LINEAR_SOLVER_ITER= 10

% Spatial discretization
CONV_NUM_METHOD_FLOW= FDS
MUSCL_FLOW= YES
SLOPE_LIMITER_FLOW= VENKATAKRISHNAN
VENKAT_LIMITER_COEFF= 0.05

CONV_NUM_METHOD_TURB= SCALAR_UPWIND
MUSCL_TURB= NO

% Convergence criteria
ITER= 250
CONV_FIELD= RMS_PRESSURE
CONV_RESIDUAL_MINVAL= -8
CONV_STARTITER= 10

% I/O
MESH_FORMAT= SU2
MESH_FILENAME= {mesh_file}
OUTPUT_FILES= ( RESTART, PARAVIEW, CSV )
CONV_FILENAME= history
TABULAR_FORMAT= CSV
HISTORY_OUTPUT= ( ITER, RMS_RES, LIFT, DRAG, MOMENT_Z )
SCREEN_OUTPUT= ( INNER_ITER, RMS_PRESSURE, RMS_VELOCITY-X, LIFT, DRAG )
"""

with open(cfg_file, "w") as f:
    f.write(config_text)

print(f"Executing SU2 RANS on NASA 30P-30N (4 MPI cores)...")
t0 = time.time()
cmd = ["mpirun", "-n", "4", su2.SU2_CFD_BIN, cfg_file]
log_file = os.path.join(workdir, "su2.log")

with open(log_file, "w") as lf:
    proc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, timeout=600, cwd=workdir)
runtime = round(time.time() - t0, 2)

res = su2.parse_su2_history(history_file, ref_chord_main=1.0, ref_chord_assembly=1.2)
res['runtime_s'] = runtime
res['exit_code'] = proc.returncode

# Published Experimental reference
CL_exp = 2.167
CD_exp = 0.0332

cl_cfd = res.get('Cl')
cd_cfd = res.get('Cd')

err_cl = ((cl_cfd - CL_exp) / CL_exp * 100.0) if cl_cfd else None
err_cd = ((cd_cfd - CD_exp) / CD_exp * 100.0) if cd_cfd else None

summary = {
    'Configuration': 'NASA 30P-30N (3-Element High-Lift)',
    'Reynolds_Number': re_val,
    'Alpha_deg': alpha_deg,
    'SU2_CL': round(cl_cfd, 4) if cl_cfd else None,
    'NASA_Exp_CL': CL_exp,
    'CL_Error_pct': round(err_cl, 2) if err_cl is not None else None,
    'SU2_CD': round(cd_cfd, 5) if cd_cfd else None,
    'NASA_Exp_CD': CD_exp,
    'CD_Error_pct': round(err_cd, 2) if err_cd is not None else None,
    'Converged': res.get('converged'),
    'Residual_Drop': res.get('residual_drop'),
    'Runtime_s': runtime
}

df = pd.DataFrame([summary])
out_csv = os.path.join(HERE, "step4_nasa_30p30n_results.csv")
df.to_csv(out_csv, index=False)
print(f"\n30P-30N Benchmark Complete. Saved to {out_csv}")
print(df.to_string())
