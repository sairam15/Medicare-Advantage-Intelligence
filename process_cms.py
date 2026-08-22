import csv, json, re
from collections import defaultdict
import os

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "cms_data")

def read_summary(path, overall_col):
    result = {}
    with open(path, encoding='utf-8-sig') as f:
        lines = f.readlines()
    reader = csv.DictReader(lines[1:])
    for row in reader:
        cid = row['Contract Number'].strip()
        if not cid:
            continue
        result[cid] = {
            'contractName': row.get('Contract Name', '').strip(),
            'orgName': row.get('Organization Marketing Name', '').strip(),
            'parentOrg': row.get('Parent Organization', '').strip(),
            'orgType': row.get('Organization Type', '').strip(),
            'overall': row.get(overall_col, '').strip(),
        }
    return result

def parse_stars(s):
    try:
        return float(str(s).replace(' stars', '').strip())
    except:
        return None

print("Reading 2026 summary ratings...")
summary_2026 = read_summary(
    os.path.join(DATA, "2026 Star Ratings Data Table - Summary Ratings (Oct 8 2025).csv"),
    "2026 Overall"
)
print(f"  {len(summary_2026)} contracts")

print("Reading 2025 summary ratings...")
summary_2025 = read_summary(
    os.path.join(DATA, "2025 Star Ratings Data Table - Summary Ratings (Dec 2 2024).csv"),
    "2025 Overall"
)
print(f"  {len(summary_2025)} contracts")

# Call center measure column indices (0-based, from row 3 of measure stars CSV)
CC_COLS = {
    'C22': 26,  # Getting Needed Care
    'C23': 27,  # Getting Appointments and Care Quickly
    'C24': 28,  # Customer Service
    'C28': 32,  # Complaints about the Health Plan
    'C29': 33,  # Members Choosing to Leave the Plan
    'C31': 35,  # Plan Makes Timely Decisions about Appeals
    'C33': 37,  # Call Center – Foreign Language Interpreter and TTY
    'D01': 38,  # Part D Call Center Language Access
    'D02': 39,  # Complaints about the Drug Plan
    'D03': 40,  # Members Choosing to Leave the Drug Plan
}

print("Reading measure stars...")
measure_stars = {}
with open(os.path.join(DATA, "2026 Star Ratings Data Table - Measure Stars (Oct 8 2025).csv"), encoding='utf-8-sig') as f:
    lines = f.readlines()
for row in csv.reader(lines[3:]):
    if not row or not row[0].strip():
        continue
    cid = row[0].strip()
    scores = {}
    for code, idx in CC_COLS.items():
        if idx < len(row):
            val = row[idx].strip()
            try:
                scores[code] = float(val)
            except:
                scores[code] = None
    measure_stars[cid] = scores
print(f"  {len(measure_stars)} contracts with measure data")

print("Reading enrollment data (large file — please wait)...")
enrollment_by_contract = defaultdict(int)
# Service-area footprint is derived from the CPSC enrollment file, which records where members
# *reside* (by county), not the CMS-approved service area. Two kinds of noise inflate a plan's
# state list and must be excluded:
#   1. SUPPRESSED counties — CMS masks county enrollment of 1-10 with "*" for beneficiary privacy.
#      A state whose every county is suppressed is a de minimis presence (a handful of members).
#   2. TRIVIAL reportable tails — CMS reports any count >=11, so relocated retirees/duals scatter a
#      plan across states it does not actually serve (e.g. BCBS Michigan showed 47 states — 86% of
#      its members are in MI, with tails like AK=15, VT=11 members). These are real numbers but not
#      a real market.
# Rule: a state counts as service area only if it holds >= FOOTPRINT_MIN_SHARE of the plan's total
# members. Everything below that (suppressed-only OR trivial reportable) is routed to marginalStates.
# A safety net always keeps each plan's single largest state so nothing is ever zeroed out.
FOOTPRINT_MIN_SHARE = 0.01  # 1% of the plan's members
state_members_by_contract = defaultdict(lambda: defaultdict(int))  # cid -> state -> reportable members
suppressed_states_by_contract = defaultdict(set)                    # states with only suppressed ("*") counties
enr_path = os.path.join(DATA, "CPSC_Enrollment_2025_05/CPSC_Enrollment_Info_2025_05.csv")
with open(enr_path, encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        cid = row['Contract Number'].strip().strip('"')
        state = row['State'].strip().strip('"')
        enr = row['Enrollment'].strip().strip('"')
        try:
            n = int(enr)
        except:
            n = None
        if state:
            if n is not None:
                state_members_by_contract[cid][state] += n
            else:
                suppressed_states_by_contract[cid].add(state)
        if n is not None:
            enrollment_by_contract[cid] += n
# Decide service-area vs marginal per state using the >=1% share rule (largest state always kept).
states_by_contract = defaultdict(set)          # states meeting the service-area threshold
for cid, sm in state_members_by_contract.items():
    total_m = enrollment_by_contract[cid] or 1
    top_state = max(sm, key=sm.get) if sm else None
    for st, m in sm.items():
        if st == top_state or (m / total_m) >= FOOTPRINT_MIN_SHARE:
            states_by_contract[cid].add(st)
        else:
            suppressed_states_by_contract[cid].add(st)  # reportable but de minimis -> marginal footprint
# A state that qualified as service area must not also appear in the marginal set.
for cid, real in states_by_contract.items():
    suppressed_states_by_contract[cid] -= real
print(f"  {len(enrollment_by_contract)} contracts with enrollment data")

print("Reading contract info...")
contract_info = {}
ci_path = os.path.join(DATA, "CPSC_Enrollment_2025_05/CPSC_Contract_Info_2025_05.csv")
with open(ci_path, encoding='latin-1') as f:
    reader = csv.DictReader(f)
    for row in reader:
        cid = row['Contract ID'].strip().strip('"')
        if cid not in contract_info:
            contract_info[cid] = {
                'orgName': row.get('Organization Marketing Name', '').strip().strip('"'),
                'planName': row.get('Plan Name', '').strip().strip('"'),
                'parentOrg': row.get('Parent Organization', '').strip().strip('"'),
                'orgType': row.get('Organization Type', '').strip().strip('"'),
            }
print(f"  {len(contract_info)} contracts in enrollment file")

# All CMS-rated plan types to include
# Local/Regional CCP = Medicare Advantage (HMO, PPO, PFFS)
# PDP = Medicare Part D standalone drug plans
# 1876 Cost = Medicare Cost plans
# PFFS = Private Fee For Service
INCLUDE_TYPES = {
    'Local CCP', 'Regional CCP', 'PDP',
    '1876 Cost', 'PFFS', 'MSA',
    'Employer/Union Only Direct Contract PDP'
}

print("\nBuilding combined dataset (all plan types, enrollment >= 500)...")
plans_out = []
for cid, s26 in summary_2026.items():
    org_type = s26['orgType']
    if not any(t in org_type for t in INCLUDE_TYPES):
        continue
    overall26 = parse_stars(s26['overall'])
    if overall26 is None:
        continue
    overall25 = parse_stars(summary_2025.get(cid, {}).get('overall', ''))
    enr = enrollment_by_contract.get(cid, 0)
    # 500-member floor removes truly zero-enrollment/test contracts only
    if enr < 500:
        continue
    states = sorted(states_by_contract.get(cid, []))
    marginal_states = sorted(suppressed_states_by_contract.get(cid, []))
    ms = measure_stars.get(cid, {})
    ci = contract_info.get(cid, {})
    org_name = ci.get('orgName', '') or s26['orgName']
    parent = ci.get('parentOrg', '') or s26['parentOrg']
    contract_name = s26.get('contractName', '')  # CMS legal contract entity name (human-readable, unlike the H##### id)

    valid_measures = {k: v for k, v in ms.items() if v is not None}
    cc_avg = (sum(valid_measures.values()) / len(valid_measures)) if valid_measures else None

    # Determine plan category
    is_pdp = 'PDP' in org_type
    is_ma  = 'CCP' in org_type or 'PFFS' in org_type or 'Cost' in org_type or 'MSA' in org_type

    plans_out.append({
        'id': cid,
        'orgName': org_name,
        'contractName': contract_name,
        'parentOrg': parent,
        'orgType': org_type,
        'planCategory': 'PDP' if is_pdp else 'MA',
        'overall2026': overall26,
        'overall2025': overall25,
        'enrollment': enr,
        'states': states,
        'marginalStates': marginal_states,  # only suppressed (1-10 member) presence, not service area
        'measures': valid_measures,
        'ccAvg': round(cc_avg, 2) if cc_avg else None,
    })

plans_out.sort(key=lambda x: -x['enrollment'])

from collections import Counter
by_type = Counter(p['planCategory'] for p in plans_out)
print(f"Total plans: {len(plans_out)}  (MA: {by_type['MA']}, PDP: {by_type['PDP']})")

print("\nTop 30 by enrollment:")
for p in plans_out[:30]:
    diff = f"prev:{p['overall2025']}" if p['overall2025'] else "new  "
    cc = f"CC:{p['ccAvg']:.1f}" if p['ccAvg'] else "CC:n/a"
    drop = " ▼DROP" if (p['overall2025'] and p['overall2026'] < p['overall2025']) else ""
    print(f"  {p['id']:8} {p['enrollment']:>9,}  {p['overall2026']}★  {cc}  {diff}  {len(p['states'])}st{drop}  {p['orgName'][:38]}")

out_path = os.path.join(BASE, "cms_plans_processed.json")
with open(out_path, "w") as f:
    json.dump(plans_out, f, indent=2)
print(f"\nSaved {len(plans_out)} plans to cms_plans_processed.json")
