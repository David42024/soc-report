"""Independent recomputation from the generated CSV; no model or service calls."""
from pathlib import Path
import csv, json, math, statistics
p=Path(__file__).parent
rows=list(csv.DictReader((p/'synthetic-cases.csv').open(encoding='utf-8')))
d=json.loads((p/'simulation-results.json').read_text())
assert len(rows)==2400 and len({r['synthetic_id'] for r in rows})==2400
accepted=[r for r in rows if r['accepted_at_075']=='1']
errors=sum(r['type_truth']!=r['type_prediction'] for r in accepted)
assert (len(accepted),errors)==(1703,93)
assert all(r['invalid_assumed']=='0' and r['injection_flag_assumed']=='0'
    and r['both_providers_failed_assumed']=='0' for r in accepted)
means={k:statistics.mean(float(r[k]) for r in rows) for k in
    ['manual_active_minutes_assumed','guarded_active_minutes_assumed']}
hours=sum(float(r['manual_active_minutes_assumed'])-float(r['guarded_active_minutes_assumed']) for r in rows)/60
assert math.isclose(hours,d['effects']['hours'],abs_tol=1e-9)
counts={}
for policy in ['manual','guarded']:
    for outcome,field in [('response','first'),('resolution','resolved')]:
        value=sum(float(r[f'{policy}_{field}_minutes'])<=float(r[f'{outcome}_deadline_minutes']) for r in rows)
        expected=d['policies'][policy.title()][outcome+'_success']
        assert value==expected
        counts[f'{policy}_{outcome}']=value
print(json.dumps(dict(result='PASS',n=len(rows),accepted=len(accepted),accepted_type_errors=errors,
    mean_active_minutes=means,hypothetical_hours=hours,sla_counts=counts),indent=2))
