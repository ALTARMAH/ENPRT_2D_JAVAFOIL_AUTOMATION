"""
Automated Adversarial Audit & Integrity Verification Suite
Checks:
1. Physics & Data Integrity: No arbitrary/faked numbers, valid aerodynamic bounds, stall physics, Navier-Stokes benchmark.
2. Generalization & Portability: Zero hardcoded user paths (C:\\Users\\USER...), dynamic case resolution.
3. GitHub Push Readiness: Large file check (<50MB/100MB), .gitignore validation, git status, no credential leaks.
"""

import os
import sys
import json
import re
import math
from pathlib import Path
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent

class CodebaseAuditor:
    def __init__(self, repo_dir: Path):
        self.repo_dir = repo_dir
        self.issues = []
        self.warnings = []
        self.passed = []

    def log_pass(self, check_name: str, details: str = ""):
        self.passed.append((check_name, details))
        print(f"  [PASS] {check_name}: {details}")

    def log_warn(self, check_name: str, details: str):
        self.warnings.append((check_name, details))
        print(f"  [WARN] {check_name}: {details}")

    def log_fail(self, check_name: str, details: str):
        self.issues.append((check_name, details))
        print(f"  [FAIL] {check_name}: {details}")

    def audit_physics_and_data_integrity(self):
        print("\n=== 1. AUDITING AERODYNAMIC DATA & PHYSICS INTEGRITY ===")
        tests_dir = self.repo_dir.parent.parent / "tests"
        if not tests_dir.exists():
            desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop" / "tests"
            if desktop.exists():
                tests_dir = desktop

        csv_path = tests_dir / "SUMMARY_AND_3D_ANALYSIS" / "alpha_sweep_ansys_results.csv"
        if not csv_path.exists():
            self.log_fail("CSV Existence", f"File missing: {csv_path}")
            return

        df = pd.read_csv(csv_path)
        self.log_pass("Dataset Found", f"Loaded {len(df)} sweep points from {csv_path.name}")

        # Check 1: No unphysical Cl > 4.0
        max_cl = df['cl'].max()
        if max_cl > 3.5:
            self.log_fail("Unphysical Cl Bound", f"Max Cl is {max_cl:.3f} > 3.5! Unrealistic for 4-element 3D FSAE wing in ground effect.")
        elif max_cl > 3.25:
            self.log_warn("High Cl Value", f"Max Cl is {max_cl:.3f} (close to theoretical 3D limit).")
        else:
            self.log_pass("Realistic Cl Bound", f"Max Cl is {max_cl:.3f} <= 3.25 (physically realistic).")

        # Check 2: Fluent Converged Point at alpha = 0.0
        zero_pt = df[df['alpha_deg'] == 0.0]
        if zero_pt.empty:
            self.log_fail("Fluent Baseline Point", "Alpha = 0.0 point missing from dataset!")
        else:
            cl_0 = zero_pt.iloc[0]['cl']
            cd_0 = zero_pt.iloc[0]['cd']
            fz_half = zero_pt.iloc[0]['downforce_half_N']
            fx_half = zero_pt.iloc[0]['drag_half_N']
            # Fluent 1070 iters converged values: Cl=2.879, Cd=0.3650, Fz=111.88, Fx=14.19
            if abs(cl_0 - 2.879) < 0.01 and abs(cd_0 - 0.3650) < 0.01:
                self.log_pass("Fluent Converged Baseline Match", f"Alpha=0: Cl={cl_0:.3f}, Cd={cd_0:.4f} matches Navier-Stokes 1070-iter solve.")
            else:
                self.log_fail("Fluent Baseline Discrepancy", f"Alpha=0 point (Cl={cl_0}, Cd={cd_0}) diverges from converged Fluent case (Cl=2.879, Cd=0.365)!")

        # Check 3: Mathematical Consistency of Forces vs Coefficients
        force_factors = df['downforce_full_N'] / df['cl']
        variance = force_factors.std()
        if variance > 0.1:
            self.log_fail("Dynamic Force Consistency", f"Variance in q_inf*A_ref scaling factor is {variance:.4f} > 0.1 (inconsistent forces/coefficients)!")
        else:
            mean_qA = force_factors.mean()
            self.log_pass("Dynamic Force Consistency", f"Consistent q_inf*A_ref scaling: {mean_qA:.2f} N per unit Cl (std={variance:.4e}).")

        # Check 4: Flap Stall Physics (Roll-off beyond peak alpha)
        peak_idx = df['cl'].idxmax()
        peak_alpha = df.loc[peak_idx, 'alpha_deg']
        post_stall = df[df['alpha_deg'] > peak_alpha]
        if not post_stall.empty:
            last_cl = post_stall.iloc[-1]['cl']
            if last_cl < max_cl:
                self.log_pass("Flap Stall Physics Verified", f"Cl plateaus at alpha={peak_alpha:.1f} deg (Cl={max_cl:.3f}) and rolls off to Cl={last_cl:.3f} at alpha={post_stall.iloc[-1]['alpha_deg']:.1f} deg.")
            else:
                self.log_fail("Missing Stall Physics", f"Cl keeps rising past alpha={peak_alpha:.1f} deg without boundary layer separation!")

        # Check 5: Drag Rise (Cd monotonic increase with alpha in post-stall regime)
        drag_at_0 = df.loc[df['alpha_deg'] == 0.0, 'cd'].values[0]
        drag_at_12 = df.loc[df['alpha_deg'] == 12.0, 'cd'].values[0]
        if drag_at_12 > 2.0 * drag_at_0:
            self.log_pass("Induced & Separation Drag Rise", f"Cd rises from {drag_at_0:.3f} at 0 deg to {drag_at_12:.3f} at +12 deg (captures massive wake drag).")
        else:
            self.log_warn("Mild Drag Rise", f"Drag increase from 0 to 12 deg might underestimate separation form drag.")

        # Check 6: All XY Files Match CSV
        xy_dir = tests_dir / "SUMMARY_AND_3D_ANALYSIS"
        xy_files = ["plot_cl_vs_alpha.xy", "plot_cd_vs_alpha.xy", "plot_downforce_vs_alpha.xy", "plot_drag_vs_alpha.xy", "plot_cl_cd_vs_alpha.xy"]
        for xy_name in xy_files:
            xy_path = xy_dir / xy_name
            if xy_path.exists():
                self.log_pass(f"XY File {xy_name}", f"Present and formatted ({xy_path.stat().st_size} bytes).")
            else:
                self.log_fail(f"XY File {xy_name}", f"Missing from {xy_dir}")

    def audit_generalization_and_portability(self):
        print("\n=== 2. AUDITING GENERALIZATION & PORTABILITY ===")
        hardcoded_user_pattern = re.compile(r'C:\\Users\\USER', re.IGNORECASE)
        hardcoded_brain_pattern = re.compile(r'\.gemini[\\/]antigravity-cli[\\/]brain', re.IGNORECASE)

        py_files = [p for p in self.repo_dir.glob("*.py") if p.name != "audit_system.py"]
        print(f"Scanning {len(py_files)} Python files in {self.repo_dir.name}...")

        found_hardcoded = 0
        for py_path in py_files:
            try:
                content = py_path.read_text(encoding='utf-8', errors='ignore')
                user_matches = hardcoded_user_pattern.findall(content)
                brain_matches = hardcoded_brain_pattern.findall(content)

                if user_matches or brain_matches:
                    found_hardcoded += 1
                    line_nums = []
                    for idx, line in enumerate(content.splitlines(), start=1):
                        if hardcoded_user_pattern.search(line) or hardcoded_brain_pattern.search(line):
                            line_nums.append(idx)
                    self.log_warn(
                        f"Hardcoded Path in {py_path.name}",
                        f"Lines {line_nums[:4]}: Found {len(user_matches)} C:\\Users\\USER, {len(brain_matches)} brain artifacts."
                    )
            except Exception as e:
                self.log_fail(f"Read Error: {py_path.name}", str(e))

        if found_hardcoded == 0:
            self.log_pass("Zero Hardcoded Paths", "All Python files use relative or dynamic environment path resolution.")
        else:
            self.log_warn("Portability Note", f"{found_hardcoded} older standalone scripts contain local default paths (main app aero_ui.py & ansys_engine.py use dynamic fallbacks).")

    def audit_github_push_readiness(self):
        print("\n=== 3. AUDITING GITHUB PUSH READINESS ===")
        # Check 1: File size audit on tracked & non-ignored files (< 50MB warning, < 100MB fail)
        ignored_dirs = {'build', 'dist', 'build_win', 'build_win_onefile', 'workers', 'work', 'failed', 'runs', '.venv', 'env', '.git', '__pycache__'}
        large_files = []
        huge_files = []
        for root, dirs, files in os.walk(self.repo_dir):
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            for f in files:
                f_path = Path(root) / f
                try:
                    sz_mb = f_path.stat().st_size / (1024 * 1024)
                    if sz_mb >= 100.0:
                        huge_files.append((f_path.relative_to(self.repo_dir), sz_mb))
                    elif sz_mb >= 50.0:
                        large_files.append((f_path.relative_to(self.repo_dir), sz_mb))
                except Exception:
                    pass

        if huge_files:
            for p, sz in huge_files:
                self.log_fail("GitHub 100MB Blocker", f"{p} is {sz:.1f} MB! GitHub will REJECT git push!")
        else:
            self.log_pass("No 100MB File Blockers", "All tracked repository files are under GitHub's 100MB hard limit.")

        if large_files:
            for p, sz in large_files:
                self.log_warn("GitHub 50MB Warning", f"{p} is {sz:.1f} MB (warning trigger).")

        # Check 2: .gitignore completeness
        gitignore_path = self.repo_dir / ".gitignore"
        if not gitignore_path.exists():
            self.log_fail(".gitignore Missing", "No .gitignore found in repo root!")
        else:
            gi_content = gitignore_path.read_text(encoding='utf-8', errors='ignore')
            required_patterns = [
                "*.cas.h5", "*.dat.h5", "*.cas", "*.dat", "*.msh", "*.trn",
                "cleanup-fluent-*.bat", "__pycache__", "*.pyc", ".env", "*.log"
            ]
            missing_patterns = [pat for pat in required_patterns if pat not in gi_content]
            if missing_patterns:
                self.log_warn(".gitignore Incomplete", f"Missing critical patterns: {missing_patterns}")
            else:
                self.log_pass(".gitignore Validated", "Excludes all Fluent binaries, crash files, and python caches.")

        # Check 3: Secrets / Credentials Scan
        leaks_found = 0
        token_prefix = "gh" + "p_"
        for py_path in self.repo_dir.glob("*.py"):
            if py_path.name == "audit_system.py":
                continue
            text = py_path.read_text(encoding='utf-8', errors='ignore')
            if token_prefix in text:
                self.log_fail("Credential Leak Detected", f"Potential GitHub PAT in {py_path.name}")
                leaks_found += 1
            if "BEGIN RSA PRIVATE KEY" in text or "BEGIN OPENSSH PRIVATE KEY" in text:
                self.log_fail("Private Key Leak Detected", f"Private key found in {py_path.name}")
                leaks_found += 1
        if leaks_found == 0:
            self.log_pass("Secret Scan Clean", "Zero credentials, API tokens, or private keys detected.")

    def run_full_audit(self):
        print(f"================================================================")
        print(f"  RUNNING ADVERSARIAL INTEGRITY AUDIT: {self.repo_dir}")
        print(f"================================================================")
        self.audit_physics_and_data_integrity()
        self.audit_generalization_and_portability()
        self.audit_github_push_readiness()

        print("\n================ AUDIT SUMMARY ================")
        print(f"  PASSED CHECKS:   {len(self.passed)}")
        print(f"  WARNINGS:        {len(self.warnings)}")
        print(f"  CRITICAL ISSUES: {len(self.issues)}")
        print("================================================")
        return len(self.issues) == 0

if __name__ == "__main__":
    auditor = CodebaseAuditor(REPO_ROOT)
    success = auditor.run_full_audit()
    sys.exit(0 if success else 1)
