import sys
sys.path.insert(0, '.')
from backend.app import SAMPLES, run_pipeline
from backend.visualizer import generate_dot_for_all

errors = []
for key, sample in SAMPLES.items():
    try:
        cfgs, reports = run_pipeline(sample['code'])
        dot = generate_dot_for_all(cfgs)
        total_dead = sum(
            len(b['dead_instructions'])
            for r in reports
            for b in r['dead_code']
        )
        unreach_s = sum(len(r['unreachable_structural']) for r in reports)
        unreach_c = sum(len(r['unreachable_constant_folding']) for r in reports)
        print(
            f"OK  [{key}]  "
            f"funcs={len(reports)}  "
            f"blocks={sum(r['total_blocks'] for r in reports)}  "
            f"dead={total_dead}  "
            f"unreach_struct={unreach_s}  "
            f"unreach_cp={unreach_c}"
        )
    except Exception as e:
        import traceback
        errors.append(key)
        print(f"FAIL [{key}]: {e}")
        traceback.print_exc()

print()
if errors:
    print(f"FAILED: {errors}")
    sys.exit(1)
else:
    print("All samples passed.")
