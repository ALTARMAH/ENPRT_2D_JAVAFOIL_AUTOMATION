#!/usr/bin/env python3
"""Standalone worker to run JavaFoil simulation in a separate process."""
import os
import sys
import subprocess
import shutil
import uuid
import json

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aero_auto as A

def run_simulation(cfg_json, wdir, ground_h, output_file):
    """Run JavaFoil simulation and write result to output_file."""
    try:
        cfg_data = json.loads(cfg_json)
        cfg = cfg_data['cfg']
        h = cfg_data['ground_h']
        
        # Reload airfoils in worker process
        A.AIRFOILS.update(A.load_all(A.AIRFOIL_DIR))
        A.load_store()
        
        from aero_auto import ALPHA, RE
        from aero_auto import save_failure, build_outlines
        
        uid = uuid.uuid4().hex[:8]
        wing_fn, script_fn, polar_fn = f"wing_{uid}.txt", f"script_{uid}.jfs", f"polar_{uid}.txt"
        wing = os.path.join(wdir, wing_fn)
        script = os.path.join(wdir, script_fn)
        polar = os.path.join(wdir, polar_fn)
        logf = os.path.join(wdir, f"java_{uid}.log")
        
        try:
            with open(wing, "w") as f:
                f.write("Automated Multi-Element Wing\n")
                for i, o in enumerate(build_outlines(cfg, h)):
                    if i > 0:
                        f.write("9999.9 9999.9\n")
                    for pt in o:
                        f.write(f"{pt[0]:.6f} {pt[1]:.6f}\n")
            
            a0, a1, st = ALPHA
            with open(script, "w") as f:
                f.write(f"""Options.Country(10);
Geometry.Open("{wing_fn}");
Options.MachNumber(0);
Options.StallModel(0);
Options.TransitionModel(1);
Options.GroundEffect({1 if h is not None else 0});
Options.HeightOverSpan(0.5);
Options.AspectRatio(0);
Options.SweepAngle(0.0);
Polar.Analyze({RE:g},{RE:g},{RE:g},{a0:g},{a1:g},{st:g},100,100,0,0);
Polar.Save("{polar_fn}");
JavaFoil.Exit();
""")
            if shutil.which("faketime"):
                cmd = ["faketime", "-f", A.safe_date_str, "java", "-client", "-Xverify:none", "-XX:TieredStopAtLevel=1",
                       "-jar", A.JAVAFOIL_JAR, f"Script={script_fn}"]
            else:
                cmd = ["java", "-client", "-Xverify:none", "-XX:TieredStopAtLevel=1",
                       "-jar", A.JAVAFOIL_JAR, f"Script={script_fn}"]
            
            timed_out = False
            with open(logf, "w") as jl:
                proc = subprocess.Popen(cmd, cwd=wdir, stdout=jl, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    proc.wait(timeout=A.RUN_TIMEOUT)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    timed_out = True
            
            diag = [f"cwd: {wdir}", f"exit code: {proc.returncode}"]
            try:
                with open(logf, errors="ignore") as lf:
                    diag += [l.rstrip() for l in lf.read().splitlines() if l.strip()][:8]
            except OSError:
                pass
            
            if timed_out:
                result = (None, "JavaFoil Timeout", diag)
            elif not (os.path.exists(polar) and os.path.getsize(polar) > 0):
                result = (None, "No Output File", diag)
            else:
                try:
                    result = A.polar_metrics(polar)
                except Exception as e:
                    result = (None, f"Parse Error: {e}", diag)
            
            if result[1] != "Valid":
                save_failure(uid, wdir, (wing, script, polar, logf), cmd)
            
            # Write result
            with open(output_file, 'w') as f:
                json.dump({'result': result}, f)
                
        finally:
            for f in (wing, script, polar, logf):
                if os.path.exists(f):
                    try: os.remove(f)
                    except OSError: pass
                    
    except Exception as e:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
            with open(output_file, 'w') as f:
                json.dump({'result': (None, f"Worker Error: {e}", [str(e)])}, f)
        except Exception:
            pass

if __name__ == '__main__':
    if len(sys.argv) != 5:
        print("Usage: _sim_worker.py <cfg_json> <wdir> <ground_h> <output_file>")
        sys.exit(1)
    ground_h = float(sys.argv[3]) if sys.argv[3] != 'None' else None
    run_simulation(sys.argv[1], sys.argv[2], ground_h, sys.argv[4])
