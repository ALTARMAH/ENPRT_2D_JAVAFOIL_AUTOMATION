import os, sys, time
import aero_auto as A
import aero_ui

def run_tests():
    print("Testing App initialization...", flush=True)
    app = aero_ui.App()
    app.withdraw()

    print("Testing Configure navigation...", flush=True)
    app.notebook.select(app.tab_cfg)
    app.on_go_to_graphs()
    assert app.notebook.select() == str(app.tab_gr), "Failed to switch to Graphs"
    print("  -> on_go_to_graphs OK", flush=True)

    app.notebook.select(app.tab_cfg)
    app.on_send_configure_to_optimizer()
    assert app.notebook.select() == str(app.tab_opt), "Failed to switch to Optimizer"
    assert app._opt_base_cfg is not None, "Base config not transferred"
    print("  -> on_send_configure_to_optimizer OK", flush=True)

    print("Testing Optimizer objectives & scoring...", flush=True)
    mock_row = {
        'Cl_a0': -3.2,
        'Cd_a0': 0.95,
        'Max_LD': 3.37,
        'Downforce_N': 260.0,
        'Drag_N': 77.0,
        'Stall_Angle': -14.0,
        'Cl_am2': -3.0,
        'Cl_ap2': -3.35,
        'Score': 85.0,
        'Score_Balanced': 85.0
    }
    base_mock = dict(mock_row)

    goals = [
        ('cl_alpha_stability', 'Cl Alpha Stability (Pitch Dive Robustness)'),
        ('max_cl_stable', 'Max Cl with Alpha Stability (High Downforce + Margin >= 3.5°)'),
        ('linear_pitch', 'Linear Pitch Gradient (Predictable Handling & Balance)'),
        ('stall_proof', 'Stall-Proof High Downforce (Zero Stall within 4.0°)'),
        ('alpha_stable_efficiency', 'Alpha-Stable Efficiency (Max L/D with Pitch Margin)'),
        ('downforce', 'Maximum Downforce (Max Cl)'),
        ('efficiency', 'Maximum Aerodynamic Efficiency (Max L/D)'),
        ('balanced', 'Balanced Multi-Objective (FSAE Competition Standard)'),
        ('compact', 'Compact Packaging (Minimize Envelope, Keep Cl)'),
    ]

    for key, goal_str in goals:
        app.opt_goal_mode.set(goal_str)
        app._on_opt_goal_changed()
        score = app._calculate_optimizer_score(mock_row, key, base_mock, retention_pct=5.0)
        assert isinstance(score, float) and score > 0, f"Invalid score for {key}: {score}"
        print(f"  -> Goal {key}: Score = {score:.2f}", flush=True)

    print("Testing Famous Wings source link...", flush=True)
    p = A.FAMOUS_PACKAGES[0]
    app._on_comb_select(pkg_id=p['id'])
    txt = app.comb_desc_txt.get('1.0', 'end')
    assert p['source_url'] in txt, "Source URL missing from details"
    assert p['source_title'] in txt, "Source Title missing from details"

    import webbrowser
    opened = []
    orig_open = webbrowser.open
    try:
        webbrowser.open = lambda u: opened.append(u)
        app._comb_open_source_url()
        assert opened == [p['source_url']], f"Expected {p['source_url']}, got {opened}"
        print(f"  -> Open Source Link opened: {opened[0]}", flush=True)
    finally:
        webbrowser.open = orig_open

    print("ALL UI METHOD TESTS PASSED SUCCESSFULLY!", flush=True)
    try:
        app.destroy()
    except Exception:
        pass
    os._exit(0)

if __name__ == '__main__':
    run_tests()
