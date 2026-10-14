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

    print("Testing Optimizer candidate table & actions...", flush=True)
    c1 = {
        'iter': 'Base', 'tag': '[BASE]', 'cfg': ('be122-125', [('be122-125', 30.0, -8.0, 100.0, 5.0)]),
        'score': 100.0, 'downforce': 250.0, 'drag': 75.0, 'ld': 3.33, 'stall_angle': -14.0,
        'margin': 4.0, 'row': {'Status': 'Valid', 'Cl_a0': -3.1, 'Cd_a0': 0.93}, 'status': 'Valid',
        'flaps_desc': 'be122-125 (-8.0°, 30.0%)'
    }
    c2 = {
        'iter': '1', 'tag': '[BEST]', 'cfg': ('be122-125', [('be122-125', 32.0, -12.0, 105.0, 8.0)]),
        'score': 125.5, 'downforce': 275.0, 'drag': 78.0, 'ld': 3.52, 'stall_angle': -15.0,
        'margin': 5.0, 'row': {'Status': 'Valid', 'Cl_a0': -3.4, 'Cd_a0': 0.96}, 'status': 'Valid',
        'flaps_desc': 'be122-125 (-12.0°, 32.0%)'
    }
    app._handle_opt_candidate(c1)
    app._handle_opt_candidate(c2)
    children = app.opt_tree.get_children()
    assert len(children) == 2, f"Expected 2 rows in opt_tree, got {len(children)}"
    print("  -> opt_tree rows inserted OK", flush=True)

    # Test candidate selection and detail display
    app.opt_tree.selection_set(children[1])
    app._on_opt_candidate_select()
    sel_cand = app._get_selected_opt_candidate()
    assert sel_cand is not None and sel_cand['iter'] == '1', "Failed to retrieve selected candidate"
    print("  -> candidate selection OK", flush=True)

    # Test apply selected candidate to Configure (Tab 1)
    app._opt_apply_candidate_to_config()
    assert app.notebook.select() == str(app.tab_cfg), "Failed to switch to Configure tab"
    cfg_applied = app.read_cfg()
    assert cfg_applied is not None, "Failed to read applied config"
    assert cfg_applied[0] == 'be122-125'
    assert cfg_applied[1][0][2] == -12.0, f"Expected angle -12.0, got {cfg_applied[1][0][2]}"
    print("  -> apply candidate to Configure (Tab 1) OK", flush=True)

    # Test set candidate as baseline
    app.notebook.select(app.tab_opt)
    app._opt_set_candidate_as_base(c2)
    assert app._opt_base_cfg == c2['cfg'], "Base config not updated to candidate"
    print("  -> set candidate as baseline OK", flush=True)

    print("ALL UI METHOD TESTS PASSED SUCCESSFULLY!", flush=True)
    try:
        app.destroy()
    except Exception:
        pass
    os._exit(0)

if __name__ == '__main__':
    run_tests()
