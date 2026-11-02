import subprocess
from pathlib import Path

fluent_exe = r"C:\Program Files\ANSYS Inc\v241\fluent\ntbin\win64\fluent.exe"

journal = """; Test Fluent Journal
/file/read-case "test_evo1.msh"
/define/models/viscous/kw-sst? yes
/define/materials/change-create air air yes constant 1.225 yes constant 1.7894e-5 no no no
/define/boundary-conditions/velocity-inlet *inlet* no no yes yes no 22.222 no 0 no no no yes 5 10
/define/boundary-conditions/pressure-outlet *outlet* yes no 0 no yes no no yes 5 10
/define/boundary-conditions/wall *ground* yes motion-bc-moving yes no 22.222 no 0 no no no no
/define/boundary-conditions/wall *top* no no no no no no
/define/boundary-conditions/wall *wing* no no no no no no
/report/reference-values/area 0.2826
/report/reference-values/length 0.498
/report/reference-values/density 1.225
/report/reference-values/velocity 22.222
/solve/initialize/hyb-initialization
/solve/iterate 50
/report/forces/wall-forces yes 0 1 (*wing*) "test_evo1_lift.txt"
/report/forces/wall-forces yes 1 0 (*wing*) "test_evo1_drag.txt"
/file/write-case-data "test_evo1_solved.cas.h5"
/exit yes
"""

with open("test_solve.jou", "w") as f:
    f.write(journal)

cmd = [fluent_exe, "2ddp", "-g", "-t4", "-i", "test_solve.jou"]
print("Running Fluent test solve...")
res = subprocess.run(cmd, capture_output=True, text=True)
print("Fluent exit code:", res.returncode)
lines = res.stdout.splitlines()
print("STDOUT tail:")
for l in lines[-25:]:
    print("  ", l)
