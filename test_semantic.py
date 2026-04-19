import sys
sys.path.insert(0, '.')
from backend.app import SAMPLES, run_pipeline

checks = {
    'dead_assignment': {
        'dead_vars': {'x'},
        'unreachable_struct': 0,
    },
    'constant_branch': {
        'unreachable_struct': 1,
    },
    'after_return': {
        'unreachable_struct': 1,
    },
    'while_const': {
        'unreachable_struct': 1,
        'dead_vars_include': {'unused'},
    },
    'liveness_demo': {
        'dead_vars_include': {'w', 'v'},
    },
}

all_ok = True
for key, expected in checks.items():
    cfgs, reports = run_pipeline(SAMPLES[key]['code'])
    dead_vars = {
        d['defined_var']
        for r in reports
        for b in r['dead_code']
        for d in b['dead_instructions']
        if d['defined_var']
    }
    total_us = sum(len(r['unreachable_structural']) for r in reports)
    total_cp = sum(len(r['unreachable_constant_folding']) for r in reports)

    ok = True
    if 'dead_vars' in expected and not expected['dead_vars'].issubset(dead_vars):
        print('FAIL [{}] expected dead_vars {} subset of {}'.format(
            key, expected['dead_vars'], dead_vars))
        ok = False
    if 'dead_vars_include' in expected:
        for v in expected['dead_vars_include']:
            if v not in dead_vars:
                print('FAIL [{}] expected var {!r} in dead_vars, got {}'.format(
                    key, v, dead_vars))
                ok = False
    if 'unreachable_struct' in expected and total_us != expected['unreachable_struct']:
        print('FAIL [{}] unreachable_struct={}, expected {}'.format(
            key, total_us, expected['unreachable_struct']))
        ok = False
    if 'unreachable_cp' in expected and total_cp != expected['unreachable_cp']:
        print('FAIL [{}] unreachable_cp={}, expected {}'.format(
            key, total_cp, expected['unreachable_cp']))
        ok = False
    if ok:
        print('SEMANTIC OK [{}]  dead_vars={}  unreach_struct={}  unreach_cp={}'.format(
            key, sorted(dead_vars), total_us, total_cp))
    else:
        all_ok = False

print()
if all_ok:
    print('All semantic checks passed.')
else:
    sys.exit(1)
