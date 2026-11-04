"""Synthetic engineering scenarios only. No provider or analyst performance measured."""
from pathlib import Path
import csv, hashlib, json, math, platform, sys
import numpy as np

OUT = Path(__file__).parent
ROOT = next((p for p in OUT.parents if (p/'backend/main.py').is_file()), None)
SEED, N, REPS = 20261103, 2400, 2000
rng = np.random.default_rng(SEED)
truth = np.repeat(np.arange(10), N // 10)
rng.shuffle(truth)
severity = rng.choice(4, N, p=[.15, .25, .45, .15])
response_due = np.array([15., 60., 240., 480.])[severity]
resolution_due = np.array([240., 480., 1440., 2880.])[severity]
group = rng.choice(3, N, p=[.70, .20, .10])
confidence = np.select([group == 0, group == 1],
    [rng.uniform(.80, .99, N), rng.uniform(.60, .80, N)], rng.uniform(.25, .60, N))
correct = rng.random(N) < np.array([.96, .80, .55])[group]
wrong = (truth + rng.integers(1, 10, N)) % 10
prediction = np.where(correct, truth, wrong)
invalid = rng.random(N) < .03
injection = rng.random(N) < .02
primary_fail = rng.random(N) < .08
backup_fail = rng.random(N) < .25
both_fail = primary_fail & backup_fail
forced = invalid | injection | both_fail
base_wait = response_due * rng.lognormal(math.log(.65), .65, N)
manual_active = rng.lognormal(math.log(12.), .45, N)
verify_active = rng.lognormal(math.log(2.), .35, N) + .5
review_active = rng.lognormal(math.log(9.), .45, N) + .5
latency = rng.lognormal(math.log(2.), .4, N)
latency = np.where(primary_fail, 25 + rng.lognormal(math.log(3.), .4, N), latency)
latency = np.where(both_fail, 50., latency)
remediation = resolution_due * rng.lognormal(math.log(.50), .45, N)
human_correct = rng.random(N) < .98

def metrics(threshold, shifted=False):
    accept = (~forced) & (confidence >= threshold)
    if shifted:
        # Same marginal correctness, but shuffled confidence destroys its usefulness.
        shifted_conf = np.random.default_rng(SEED + 4).permutation(confidence)
        accept = (~forced) & (shifted_conf >= threshold)
    risk = float((~correct[accept]).mean()) if accept.any() else None
    active = np.where(accept, verify_active, review_active)
    first = base_wait * np.where(accept, .35, .95) + active + latency/60
    resolved = first + remediation
    final = np.where(accept, prediction, np.where(human_correct, truth, wrong))
    return dict(threshold=threshold, accepted=int(accept.sum()), review=int((~accept).sum()),
        coverage=float(accept.mean()), risk=risk, accuracy=float((final == truth).mean()),
        active=float(active.mean()), response=float((first <= response_due).mean()),
        resolution=float((resolved <= resolution_due).mean())), active, first, resolved, accept

main, assisted_active, assisted_first, assisted_resolved, accept = metrics(.75)
manual_first = base_wait + manual_active
manual_resolved = manual_first + remediation
unguarded_first = base_wait*.35 + verify_active + latency/60
unguarded_resolved = unguarded_first + remediation
policies = {
    'Manual': (manual_active, manual_first, manual_resolved),
    'Unguarded': (verify_active, unguarded_first, unguarded_resolved),
    'Guarded': (assisted_active, assisted_first, assisted_resolved),
}
policy_summary = {}
for name, (active, first, resolved) in policies.items():
    policy_summary[name] = dict(active_mean=float(active.mean()), active_median=float(np.median(active)),
        first_mean=float(first.mean()), resolution_mean=float(resolved.mean()),
        response_success=int((first <= response_due).sum()), resolution_success=int((resolved <= resolution_due).sum()),
        response=float((first <= response_due).mean()), resolution=float((resolved <= resolution_due).mean()))

# Paired percentile bootstrap. These intervals quantify sampling under assumptions only.
boot_rng = np.random.default_rng(SEED + 1)
diff_active, diff_response, diff_resolution = [], [], []
for _ in range(REPS):
    ix = boot_rng.integers(0, N, N)
    diff_active.append(float((manual_active[ix] - assisted_active[ix]).mean()))
    diff_response.append(float(((assisted_first[ix] <= response_due[ix]).astype(float)
        - (manual_first[ix] <= response_due[ix])).mean())*100)
    diff_resolution.append(float(((assisted_resolved[ix] <= resolution_due[ix]).astype(float)
        - (manual_resolved[ix] <= resolution_due[ix])).mean())*100)

def interval(x): return [float(t) for t in np.quantile(x, [.025, .975])]
effects = dict(active_minutes=float(np.mean(manual_active - assisted_active)),
    active_ci=interval(diff_active), hours=float(np.sum(manual_active-assisted_active)/60),
    hours_ci=[x*N/60 for x in interval(diff_active)],
    response_pp=(main['response']-policy_summary['Manual']['response'])*100,
    response_ci=interval(diff_response),
    resolution_pp=(main['resolution']-policy_summary['Manual']['resolution'])*100,
    resolution_ci=interval(diff_resolution))

thresholds = [metrics(t)[0] for t in [0., .60, .70, .75, .80, .90, .95]]
shifted = [metrics(t, True)[0] for t in [0., .60, .70, .75, .80, .90, .95]]
# Reviewer-capacity sensitivity adds a stipulated extra wait only to referred cases.
capacity = []
for extra in [0, 15, 30, 60, 120, 240]:
    first = assisted_first + (~accept)*extra
    capacity.append(dict(extra_minutes=extra, response=float((first<=response_due).mean()),
        resolution=float((first+remediation<=resolution_due).mean())))

# Independent fluid recovery model. Not a throughput measurement of FastAPI/n8n.
time = np.arange(0, 121)
recoveries = []
for rate, capacity_rate in [(6, 20), (18,20), (22,20)]:
    backlog = 0.
    line = []
    for minute in time:
        line.append(backlog)
        service = 0 if minute < 30 else capacity_rate
        backlog = max(0., backlog + rate - service)
    recoveries.append(dict(arrivals_per_min=rate, service_per_min=capacity_rate, backlog=line,
        theoretical_drain_min=(30*rate/(capacity_rate-rate)) if rate < capacity_rate else None))

data = dict(label='SYNTHETIC SCENARIOS NOT FIELD EVIDENCE', seed=SEED, n=N,
    bootstrap_replicates=REPS, numpy=np.__version__, python=platform.python_version(),
    severity_counts=np.bincount(severity, minlength=4).tolist(),
    forced_counts=dict(invalid=int(invalid.sum()), injection=int(injection.sum()),
        primary_fail=int(primary_fail.sum()), backup_used=int((primary_fail & ~backup_fail).sum()),
        both_fail=int(both_fail.sum()), union=int(forced.sum())),
    nominal_raw_accuracy=float(correct.mean()), main=main, policies=policy_summary,
    effects=effects, thresholds=thresholds, shifted=shifted, reviewer_capacity=capacity,
    recovery=recoveries)
(OUT/'simulation-results.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
with (OUT/'synthetic-cases.csv').open('w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['synthetic_id','type_truth','severity_index','confidence_assumed','type_prediction',
        'invalid_assumed','injection_flag_assumed','both_providers_failed_assumed','accepted_at_075',
        'manual_active_minutes_assumed','guarded_active_minutes_assumed','response_deadline_minutes',
        'resolution_deadline_minutes','manual_first_minutes','guarded_first_minutes',
        'manual_resolved_minutes','guarded_resolved_minutes'])
    for i in range(N):
        writer.writerow([f'SYN-{i+1:04}',int(truth[i]),int(severity[i]),confidence[i],int(prediction[i]),
            int(invalid[i]),int(injection[i]),int(both_fail[i]),int(accept[i]),manual_active[i],
            assisted_active[i],response_due[i],resolution_due[i],manual_first[i],assisted_first[i],
            manual_resolved[i],assisted_resolved[i]])

files = ['backend/main.py','backend/classifier.py','backend/db.py','backend/runtime.py',
    'backend/impact_study.py','backend/security.py','db/schema.sql','integrations/reglas.json',
    'integrations/langflow/cloud_classifier_model.py','integrations/n8n/assign_report.json',
    'docs/diseno/ronda-2/pruebas-despues.log',
    '.venv/soc-runtime/test-results/soc-tests-20261103-161108.log']
if ROOT:
    manifest = {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        if (ROOT/name).is_file() else 'NOT AVAILABLE IN CURRENT CHECKOUT' for name in files}
    (OUT/'source-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
assert sum(data['severity_counts']) == N
assert main['accepted'] + main['review'] == N
assert np.all(assisted_resolved >= assisted_first)
assert not np.any(accept & forced)
assert data['nominal_raw_accuracy'] < 1
print(json.dumps(dict(main=main, effects=effects, policies=policy_summary,
    forced_counts=data['forced_counts'], severity_counts=data['severity_counts']),indent=2))
