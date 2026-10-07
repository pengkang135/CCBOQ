"""
Resource three-level taxonomy: 【人工/主材/周转材/辅材/机械】→《种类》→{子类}.

Two config files, both under config/:
  resource_taxonomy.json      the taxonomy itself — keyword tree, ordering, fixes, rules
  resource_classification.json a name → category cache, appended to as new names appear

classify_resource() checks the cache first, falls back to the rules, and remembers the
answer. Callers must call save_classification_dict() to persist what they added.
"""
import json
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent / 'config'
TAXONOMY_PATH = CONFIG_DIR / 'resource_taxonomy.json'
DICT_PATH = CONFIG_DIR / 'resource_classification.json'

with open(TAXONOMY_PATH, encoding='utf-8') as f:
    _T = json.load(f)

CATEGORIES = _T['CATEGORIES']
MAIN_CAT2_ORDER = _T['MAIN_CAT2_ORDER']
MECH_CAT2_ORDER = _T['MECH_CAT2_ORDER']
MECH_SMALL_CAT3_ORDER = _T['MECH_SMALL_CAT3_ORDER']
CAT1_REMAP = _T['CAT1_REMAP']
KEYWORD_RULES = _T['KEYWORD_RULES']
FALLBACK = tuple(_T['FALLBACK'])
_FIX_TABLES = {'MECH_FIXES': _T['MECH_FIXES'], 'MATERIAL_FIXES': _T['MATERIAL_FIXES']}

FEE_TARGET = ('材料', '费用项', '其他费')
WATER_POWER = ('施工用水', '施工用电')


def load_classification_dict():
    if DICT_PATH.exists():
        with open(DICT_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_classification_dict(d):
    with open(DICT_PATH, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


CLASS_DICT = load_classification_dict()


def classify_resource(name):
    """Cache lookup first; unknown names go through the rules and are remembered."""
    hit = CLASS_DICT.get(name)
    if hit:
        return (hit['cat1'], hit['cat2'], hit['cat3'])
    result = _classify_by_keyword(name)
    CLASS_DICT[name] = {'cat1': result[0], 'cat2': result[1], 'cat3': result[2]}
    return result


def _best_by_keyword_tree(name):
    """Longest total keyword overlap across the 三级 tree wins; ties keep the first."""
    best, best_score = FALLBACK, 0
    for cat1, cat2_dict in CATEGORIES.items():
        for cat2, cat3_dict in cat2_dict.items():
            for cat3, keywords in cat3_dict.items():
                score = sum(len(kw) for kw in keywords if kw in name)
                if score > best_score:
                    best, best_score = (cat1, cat2, cat3), score
    return best


def _classify_by_keyword(name):
    """Rules run in the order they appear in KEYWORD_RULES; the tree is the fallback."""
    fallback = _best_by_keyword_tree(name)

    # 水/电 pick their 子类 from the name itself, so they can't be a table row
    if name in ('水', '电') or name in WATER_POWER:
        return ('材料', '施工临建及措施材料', WATER_POWER[0] if '水' in name else WATER_POWER[1])

    for rule in KEYWORD_RULES:
        kind = rule['m']
        if kind == 'contains':
            if any(kw in name for kw in rule['kw']):
                return tuple(rule['to'])
        elif kind == 'exact':
            if name in rule['kw']:
                return tuple(rule['to'])
        elif kind == 'fixes':
            hit = _FIX_TABLES[rule['table']].get(name)
            if hit:
                prefix = (rule['prefix'],) if 'prefix' in rule else ()
                return prefix + tuple(hit)
        elif kind == 'fee':
            # 费 alone is too broad: only 元-denominated or 费-suffixed names are costs
            if '费' in name and ('元' in name or name.endswith('费')):
                return FEE_TARGET
    return fallback
