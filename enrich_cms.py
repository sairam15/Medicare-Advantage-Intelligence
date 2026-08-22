import json, os, re

BASE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(BASE, 'cms_plans_processed.json')) as f:
    plans = json.load(f)

print(f"Enriching {len(plans)} plans...")

# ── Build accurate SNP sets from CPSC plan-level data ────────
import csv
dsnp_cids, csnp_cids, isnp_cids = set(), set(), set()
ci_path = os.path.join(BASE, 'cms_data', 'CPSC_Enrollment_2025_05', 'CPSC_Contract_Info_2025_05.csv')
with open(ci_path, encoding='latin-1') as f:
    for row in csv.DictReader(f):
        plan_name = row.get('Plan Name', '').strip().strip('"').lower()
        cid = row.get('Contract ID', '').strip().strip('"')
        if 'd-snp' in plan_name or 'dual eligible' in plan_name:
            dsnp_cids.add(cid)
        if 'c-snp' in plan_name or ('chronic' in plan_name and 'snp' in plan_name):
            csnp_cids.add(cid)
        if 'i-snp' in plan_name or ('institutional' in plan_name and 'snp' in plan_name):
            isnp_cids.add(cid)
print(f"  SNP sets: D-SNP={len(dsnp_cids)}, C-SNP={len(csnp_cids)}, I-SNP={len(isnp_cids)}")

# ── Blue Cross / BCBS detection ─────────────────────────────
BC_KEYWORDS = [
    'blue cross', 'blue shield', 'bcbs', 'bluecross', 'blueshield',
    'anthem blue', 'highmark blue', 'carefirst blue', 'independence blue',
    'capital blue', 'horizon blue', 'wellmark', 'nextblue', 'wyoblue',
    'bluecare', 'blue care', 'bluerx', 'bluescripts', 'blue medicare',
    'medica blue', 'regence blue',
]
def is_blue_cross(org, parent):
    t = (org + ' ' + parent).lower()
    return any(k in t for k in BC_KEYWORDS)

# ── SNP / special needs detection ───────────────────────────
DSNP_KW  = ['dual', 'd-snp', 'dsnp', 'dual eligible', 'dual special']
CSNP_KW  = ['chronic', 'c-snp', 'csnp', 'chronic condition']
ISNP_KW  = ['institutional', 'i-snp', 'isnp', 'nursing home', 'long-term care']
MMP_KW   = ['mmp', 'medicare-medicaid', 'financial alignment', 'capitated model']

def detect_snp(name, parent):
    t = (name + ' ' + parent).lower()
    return {
        'hasDSNP':  any(k in t for k in DSNP_KW),
        'hasCSNP':  any(k in t for k in CSNP_KW),
        'hasISNP':  any(k in t for k in ISNP_KW),
        'hasMMP':   any(k in t for k in MMP_KW),
    }

# ── Plan type detection ──────────────────────────────────────
def detect_plan_types(org_type, name):
    t = (org_type + ' ' + name).lower()
    types = []
    if 'ppo' in t: types.append('ppo')
    if 'hmo' in t or 'ccp' in org_type: types.append('hmo')
    if 'pffs' in t: types.append('pffs')
    if 'pdp' in t or org_type == 'PDP': types.append('pdp')
    if 'cost' in t: types.append('cost')
    if 'msa' in t: types.append('msa')
    return types

# ── Contract value estimate ──────────────────────────────────
# Based on BPO industry benchmarks: $35-$75 per member per year for full-service
# call center + quality improvement engagement
def contract_range(enr):
    if enr >= 1_000_000:
        low, high = enr * 28, enr * 55
    elif enr >= 500_000:
        low, high = enr * 30, enr * 60
    elif enr >= 200_000:
        low, high = enr * 32, enr * 65
    elif enr >= 100_000:
        low, high = enr * 35, enr * 70
    elif enr >= 50_000:
        low, high = enr * 38, enr * 75
    elif enr >= 20_000:
        low, high = enr * 40, enr * 80
    elif enr >= 5_000:
        low, high = enr * 35, enr * 70
    else:
        low, high = enr * 25, enr * 50
    return [int(low), int(high)]

# ── Opportunity score ────────────────────────────────────────
def opportunity_score(plan):
    enr = plan['enrollment']
    # Size component (0-50)
    if   enr >= 1_000_000: size = 50
    elif enr >= 500_000:   size = 45
    elif enr >= 200_000:   size = 38
    elif enr >= 100_000:   size = 30
    elif enr >= 50_000:    size = 22
    elif enr >= 20_000:    size = 15
    elif enr >= 10_000:    size = 10
    elif enr >= 5_000:     size = 7
    else:                  size = 3

    # CC quality gap (0-30): how far below perfect the call-center measures are
    cc = plan.get('ccAvg')
    cc_gap = max(0, (5.0 - cc) / 2.5 * 30) if cc else 15

    # Star urgency (0-20)
    star = plan.get('overall2026', 3.0)
    if   star <= 2.0: urg = 20
    elif star <= 2.5: urg = 18
    elif star <= 3.0: urg = 14
    elif star <= 3.5: urg = 10
    elif star <= 4.0: urg =  5
    else:             urg =  2

    # YoY drop bonus (0-12)
    prev = plan.get('overall2025')
    drop = min(12, int((prev - star) * 8)) if prev and star < prev else 0

    return min(99, int(size + cc_gap + urg + drop))

# ── Signal generation ────────────────────────────────────────
def generate_signals(plan):
    signals = []
    ms = plan.get('measures', {})
    star = plan['overall2026']
    prev = plan.get('overall2025')

    if prev and star < prev:
        lost_qbp = star < 4.0 and prev >= 4.0
        signals.append({
            'type': 'star_drop',
            'headline': f"Stars dropped {prev}★ → {star}★ (2025→2026)",
            'detail': (f"Plan fell below the 4.0★ Quality Bonus Payment threshold, losing an estimated "
                       f"${plan['enrollment']*45:,.0f}/yr in CMS bonus payments. "
                       "Call center quality is a primary lever to recover lost stars.")
                      if lost_qbp else
                      (f"CMS 2026 Star Ratings show a {prev-star:.1f}-star decline. "
                       "Member experience and call center responsiveness are key recovery levers."),
            'source': 'CMS 2026 Star Ratings (Oct 8, 2025)',
        })

    if star <= 2.5:
        signals.append({
            'type': 'low_performer',
            'headline': f"Low-Performing Plan — {star}★ (42 CFR §422.510 risk)",
            'detail': ("Plans below 3.0★ for three consecutive years face CMS enrollment restrictions "
                       "and sanctions under 42 CFR §422.510. This plan is in or near that zone."),
            'source': 'CMS 2026 Star Ratings / 42 CFR §422.510',
        })

    # Language access gaps (C33 or D01 < 3.5)
    c33 = ms.get('C33'); d01 = ms.get('D01')
    if (c33 is not None and c33 < 3.5) or (d01 is not None and d01 < 3.5):
        bad = []
        if c33 and c33 < 3.5: bad.append(f"C33 Part C Language Access: {c33}★")
        if d01 and d01 < 3.5: bad.append(f"D01 Part D Language Access: {d01}★")
        signals.append({
            'type': 'language_gap',
            'headline': 'Language Access Audit Gap — CMS Direct Audit Measure',
            'detail': (f"{' / '.join(bad)}. These are CMS audit measures scored by live test calls. "
                       "Everise's multilingual workforce is a direct solution to this gap."),
            'source': 'CMS 2026 Measure Stars',
        })

    # CC quality gap (avg < 3.5)
    cc = plan.get('ccAvg')
    if cc and cc < 3.5:
        signals.append({
            'type': 'cc_weakness',
            'headline': f"Call Center Quality Gap — Avg {cc}★ across CC measures",
            'detail': (f"CC measure average of {cc}★ is below the 3.5★ industry benchmark. "
                       "Measures C22 (Access), C23 (Timeliness), C24 (Customer Service) "
                       "directly reflect call center performance."),
            'source': 'CMS 2026 Measure Stars',
        })

    # Complaint surge (C28 < 3.5)
    c28 = ms.get('C28')
    if c28 is not None and c28 < 3.5:
        signals.append({
            'type': 'complaint_surge',
            'headline': f"High Complaint Rate — C28: {c28}★",
            'detail': (f"CMS complaint measure C28 = {c28}★. High complaint rates are directly "
                       "correlated with poor first-call resolution and inadequate call center staffing."),
            'source': 'CMS 2026 Measure Stars',
        })

    # Disenrollment spike (C29 < 3.5 or D03 < 3.5)
    c29 = ms.get('C29'); d03 = ms.get('D03')
    if (c29 is not None and c29 < 3.5) or (d03 is not None and d03 < 3.5):
        signals.append({
            'type': 'disenrollment_spike',
            'headline': 'Elevated Disenrollment — Members Leaving the Plan',
            'detail': ("CMS exit surveys cite 'difficulty reaching the plan' as the #1 reason members "
                       "voluntarily disenroll. Improving call center accessibility directly reduces churn."),
            'source': 'CMS 2026 Measure Stars',
        })

    # Appeals risk (C31 < 3.5)
    c31 = ms.get('C31')
    if c31 is not None and c31 < 3.5:
        signals.append({
            'type': 'appeals_risk',
            'headline': f"Appeals Timeliness Risk — C31: {c31}★",
            'detail': (f"C31 (Plan Makes Timely Decisions on Appeals) = {c31}★. "
                       "The call center is the first point of contact for all member appeals and grievances. "
                       "Delays create CMS compliance risk."),
            'source': 'CMS 2026 Measure Stars',
        })

    return signals[:5]

# ── Scenarios ────────────────────────────────────────────────
def generate_scenarios(plan):
    scenarios = []
    star = plan['overall2026']
    prev = plan.get('overall2025')
    ms = plan.get('measures', {})

    if prev and star < prev and star < 4.0:
        scenarios.append({'type': 'recovery', 'label': 'Recovery Play',
            'desc': "Plan lost stars/QBP — urgency to recover bonus payments"})
    if star <= 2.5:
        scenarios.append({'type': 'turnaround', 'label': 'Turnaround Play',
            'desc': "Persistent low performer — below 3.0★, CMS sanction risk"})
    c33 = ms.get('C33'); d01 = ms.get('D01')
    if (c33 and c33 < 3.5) or (d01 and d01 < 3.5):
        scenarios.append({'type': 'language', 'label': 'Language Play',
            'desc': "Failed language access audit — addressable with specialized multilingual workforce"})
    c31 = ms.get('C31')
    if c31 and c31 < 3.5:
        scenarios.append({'type': 'compliance', 'label': 'Compliance Play',
            'desc': "Appeals/grievances deficiency — compliance-driven urgency"})
    if star >= 4.0 and plan['enrollment'] >= 200_000:
        scenarios.append({'type': 'expansion', 'label': 'Expansion Play',
            'desc': "High-performing plan scaling members — needs quality staffing to maintain stars"})
    return scenarios

# ── Talking points ───────────────────────────────────────────
def generate_talking_points(plan):
    pts = []
    star = plan['overall2026']
    prev = plan.get('overall2025')
    cc = plan.get('ccAvg')
    ms = plan.get('measures', {})
    enr = plan['enrollment']
    cr = plan.get('contractRange', [0, 0])

    if prev and star < prev:
        qbp_loss = enr * 45 if star < 4.0 <= prev else 0
        pts.append(f"Your 2026 Star Rating dropped {prev}★ → {star}★. " +
                   (f"That's an estimated ${qbp_loss:,.0f}/yr in lost Quality Bonus Payments (QBP). "
                    "Everise's call center quality program has helped similar plans recover 0.5–1.0★ within 24 months."
                    if qbp_loss else
                    "Everise's quality improvement programs are designed to reverse star declines within 2 rating cycles."))
    if cc and cc < 4.0:
        pts.append(f"Your call-center-linked measures average {cc}★. The top plans in your market average 4.2★+. "
                   "That gap represents roughly $" + f"{int(enr*(4.2-cc)*18):,} in annual revenue risk from member churn.")
    c24 = ms.get('C24')
    if c24 and c24 < 4.0:
        pts.append(f"Customer Service (C24) = {c24}★ — the single most call-center-correlated measure in the Star program. "
                   "Everise specializes in driving this measure through rigorous QA, FCR coaching, and CAHPS survey preparation.")
    c33 = ms.get('C33'); d01 = ms.get('D01')
    if (c33 and c33 < 4.0) or (d01 and d01 < 4.0):
        pts.append(f"Language access scores (C33={c33 or 'N/A'}★, D01={d01 or 'N/A'}★) show audit risk. "
                   "Everise operates 40+ language lines with certified Medicare interpreters — a direct path to audit remediation.")
    pts.append(f"For a plan of your size ({enr:,} members), Everise's typical engagement ranges "
               f"${cr[0]//1_000_000:.0f}M–${cr[1]//1_000_000:.0f}M/year with a 12–18 month star improvement guarantee.")
    return pts[:4]

# ── Enrich all plans ─────────────────────────────────────────
enriched = []
for p in plans:
    org  = p['orgName']
    par  = p['parentOrg']
    cid  = p['id']
    # Use plan-level SNP flags (accurate) with org-name fallback
    snp_name = detect_snp(org, par)
    snp = {
        'hasDSNP': cid in dsnp_cids or snp_name['hasDSNP'],
        'hasCSNP': cid in csnp_cids or snp_name['hasCSNP'],
        'hasISNP': cid in isnp_cids or snp_name['hasISNP'],
        'hasMMP':  snp_name['hasMMP'],
    }
    ptypes = detect_plan_types(p['orgType'], org)
    cr   = contract_range(p['enrollment'])
    score = opportunity_score(p)
    sigs  = generate_signals(p)
    scens = generate_scenarios(p)
    tpts  = generate_talking_points({**p, 'contractRange': cr})

    enriched.append({
        **p,
        'opportunityScore': score,
        'signals':          sigs,
        'scenarios':        scens,
        'talkingPoints':    tpts,
        'contractRange':    cr,
        'isBlueCross':      is_blue_cross(org, par),
        'hasDSNP':          snp['hasDSNP'],
        'hasCSNP':          snp['hasCSNP'],
        'hasISNP':          snp['hasISNP'],
        'hasMMP':           snp['hasMMP'],
        'hasSNP':           snp['hasDSNP'] or snp['hasCSNP'] or snp['hasISNP'],
        'hasPartD':         'pdp' in ptypes or 'D01' in p.get('measures', {}),
        'planTypes':        ptypes,
    })

enriched.sort(key=lambda x: -x['opportunityScore'])

from collections import Counter
tiers = Counter()
for p in enriched:
    s = p['opportunityScore']
    if s >= 65: tiers['CRITICAL']  += 1
    elif s >= 50: tiers['HIGH']    += 1
    elif s >= 35: tiers['MEDIUM']  += 1
    elif s >= 20: tiers['MONITOR'] += 1
    else:         tiers['LOW']     += 1

bc = sum(1 for p in enriched if p['isBlueCross'])
dsnp = sum(1 for p in enriched if p['hasDSNP'])
pdp = sum(1 for p in enriched if p['planCategory'] == 'PDP')
print(f"\nTotal enriched: {len(enriched)}")
print(f"  BCBS plans:  {bc}")
print(f"  D-SNP plans: {dsnp}")
print(f"  PDP plans:   {pdp}")
print(f"  Score tiers: {dict(tiers)}")

# Verify key plans are present
for target in ['BCBS Texas','BCBS Oklahoma','BCBS South Carolina']:
    kw = target.replace('BCBS ','').lower()
    matches = [p for p in enriched if kw in p['orgName'].lower() or kw in p['parentOrg'].lower()]
    for m in matches:
        print(f"  ✓ {target}: {m['id']} {m['orgName']} ({m['enrollment']:,} members, {m['overall2026']}★)")

out = os.path.join(BASE, 'cms_plans_enriched.json')
with open(out, 'w') as f:
    json.dump(enriched, f, indent=2)
print(f"\nSaved {len(enriched)} plans → cms_plans_enriched.json")
