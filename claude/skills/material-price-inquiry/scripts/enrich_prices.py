import json, re, sys
from pathlib import Path
import yaml

input_path = sys.argv[1] if len(sys.argv) > 1 else 'price_data.json'
output_path = sys.argv[2] if len(sys.argv) > 2 else 'price_data_enriched.json'

# Load tariff rates from YAML (single source of truth)
script_dir = Path(__file__).resolve().parent
yaml_path = script_dir.parent / 'references' / 'tariff_rates.yaml'
with open(yaml_path, 'r', encoding='utf-8') as f:
    tariff = yaml.safe_load(f)

bd = tariff['bangladesh']
origin_factors = tariff['origin_factors']
categories = tariff['categories']

def match_category(name, mtype):
    """Match material name/type to tariff category via keyword matching."""
    text = (name + ' ' + mtype).lower()
    for cat in categories:
        for kw in cat['keywords']:
            if kw in text:
                return cat
    # Return default (last in list, id='default')
    return categories[-1]

def classify_source(rec):
    """Determine origin region and current price basis."""
    location = (rec.get('location', '') or '').lower()
    source = (rec.get('source', '') or '').lower()
    mtype = (rec.get('material_type', '') or '').lower()
    note = (rec.get('note', '') or '').lower()
    all_text = location + ' ' + source + ' ' + note + ' ' + mtype

    if any(k in all_text for k in ['bangladesh', 'bd', 'dhaka', 'chittagong', 'bwdb', 'pwd', 'tiger', 'bsrm', 'ksrm', 'bashundhara', 'fortimix', 'simex', 'bbs', 'glive', 'bdstall']):
        origin = 'BD'
    elif any(k in all_text for k in ['india', 'indiamart', 'jaipur', 'mumbai', 'pune', 'maharashtra', 'rajasthan', 'gujarat', 'delhi', 'inr', 'kolkata']):
        origin = 'IN'
    elif any(k in all_text for k in ['china', 'shandong', 'tai\'an', 'qingdao', 'fob', 'alibaba', 'made-in-china', 'cny', '¥', 'rmb']):
        origin = 'CN'
    elif any(k in all_text for k in ['turkey', 'arsan', 'kauçuk', 'uk', 'europe']):
        origin = 'EU'
    else:
        if 'inr' in all_text or '₹' in all_text:
            origin = 'IN'
        elif 'bdt' in all_text or 'tk' in all_text:
            origin = 'BD'
        elif 'cny' in all_text or '¥' in all_text:
            origin = 'CN'
        else:
            origin = 'CN'

    is_fob = any(k in all_text for k in ['fob', 'free on board', 'ex-factory', 'ex works', 'exw', 'factory price'])
    is_exw = any(k in all_text for k in ['ex-factory', 'ex works', 'exw', 'factory price', '出厂'])
    is_local = origin == 'BD' and not is_fob and not is_exw
    is_govt = any(k in all_text for k in ['schedule', 'government', 'govt', 'pwd', 'ceiling', 'bwdb'])

    if is_local:
        basis = 'DDP' if is_govt else 'CIF'
    elif is_exw:
        basis = 'EXW'
    elif is_fob or origin in ('CN', 'IN'):
        basis = 'FOB' if origin == 'CN' else 'EXW'
    else:
        basis = 'FOB'

    return origin, basis

def estimate_prices(rec):
    pu = rec.get('price_usd')
    if pu is None:
        return None, None, None, None, None

    if isinstance(pu, str):
        nums = re.findall(r'[\d.]+', pu.replace(',',''))
        if nums:
            pu = float(nums[0])
        else:
            return None, None, None, None, None

    origin, basis = classify_source(rec)

    # Match to tariff category
    name = rec.get('material_name', '')
    mtype = rec.get('material_type', '')
    cat = match_category(name, mtype)

    freight_pct = cat['freight_pct']
    CD = cat['customs_duty']
    RD = cat['regulatory_duty']
    AIT = cat['advance_income_tax']
    AT = cat['advance_tax']
    clearance = bd['clearance_pct']
    vat_rate = bd['vat_rate']
    inland = bd['inland_transport_base_usd']

    orig = origin_factors.get(origin, origin_factors['CN'])
    exw_to_fob = 1.0 + orig['exw_to_fob_pct']
    fob_to_cif = 1.0 + freight_pct * orig['freight_multiplier']
    # DDP ex-VAT = CIF × (1 + CD + AIT + AT + RD + clearance) + inland
    cif_to_ddp_exvat = 1.0 + CD + AIT + AT + RD + clearance

    if origin == 'BD':
        ddp_exvat = pu
        cif = pu / cif_to_ddp_exvat
        fob = cif / fob_to_cif
        exw = fob / exw_to_fob
    elif origin == 'CN':
        if basis == 'EXW':
            exw = pu
            fob = pu * exw_to_fob
            cif = fob * fob_to_cif
            ddp_exvat = cif * cif_to_ddp_exvat + inland
        elif basis == 'FOB':
            fob = pu
            exw = pu / exw_to_fob
            cif = fob * fob_to_cif
            ddp_exvat = cif * cif_to_ddp_exvat + inland
        else:
            fob = pu
            exw = pu / exw_to_fob
            cif = fob * fob_to_cif
            ddp_exvat = cif * cif_to_ddp_exvat + inland
    elif origin == 'IN':
        if basis == 'EXW':
            exw = pu
            fob = pu * exw_to_fob
            cif = fob * fob_to_cif
            ddp_exvat = cif * cif_to_ddp_exvat + inland
        elif basis == 'FOB':
            fob = pu
            exw = pu / exw_to_fob
            cif = fob * fob_to_cif
            ddp_exvat = cif * cif_to_ddp_exvat + inland
        else:
            exw = pu
            fob = pu * exw_to_fob
            cif = fob * fob_to_cif
            ddp_exvat = cif * cif_to_ddp_exvat + inland
    elif origin == 'EU':
        if basis == 'EXW':
            exw = pu
            fob = pu * exw_to_fob
            cif = fob * fob_to_cif
            ddp_exvat = cif * cif_to_ddp_exvat + inland
        else:
            fob = pu
            exw = pu / exw_to_fob
            cif = fob * fob_to_cif
            ddp_exvat = cif * cif_to_ddp_exvat + inland

    ddp_inc_vat = round(ddp_exvat + cif * (1.0 + CD) * vat_rate, 2)
    return round(exw, 2), round(fob, 2), round(cif, 2), round(ddp_exvat, 2), ddp_inc_vat

with open(input_path, 'r', encoding='utf-8') as f:
    all_data = json.load(f)

for rec in all_data:
    origin, basis = classify_source(rec)
    exw, fob, cif, ddp_exvat, ddp_inc_vat = estimate_prices(rec)
    name = rec.get('material_name', '')
    mtype = rec.get('material_type', '')
    cat = match_category(name, mtype)

    rec['origin'] = origin
    rec['price_basis'] = basis
    rec['price_exw'] = exw
    rec['price_fob'] = fob
    rec['price_cif'] = cif
    rec['price_ddp'] = ddp_exvat
    rec['price_ddp_inc_vat'] = ddp_inc_vat
    rec['duty_category'] = cat['id']
    rec['duty_components'] = {
        'customs_duty': cat['customs_duty'],
        'vat_rate': bd['vat_rate'],
        'advance_income_tax': cat['advance_income_tax'],
        'advance_tax': cat['advance_tax'],
        'regulatory_duty': cat['regulatory_duty'],
        'clearance': bd['clearance_pct'],
        'freight_pct': cat['freight_pct'],
        'inland_transport_usd': bd['inland_transport_base_usd'],
    }

Path(output_path).parent.mkdir(parents=True, exist_ok=True)
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(all_data, f, ensure_ascii=False, indent=2)

origins = {}
for rec in all_data:
    o = rec.get('origin', '??')
    origins[o] = origins.get(o, 0) + 1

print("Origin distribution:")
for o, c in sorted(origins.items()):
    print(f"  {o}: {c} records")

with_ddp = sum(1 for r in all_data if r.get('price_ddp') is not None)
print(f"\nDDP (ex-VAT) estimates available: {with_ddp}/{len(all_data)}")
print("Written: price_data_enriched.json")
