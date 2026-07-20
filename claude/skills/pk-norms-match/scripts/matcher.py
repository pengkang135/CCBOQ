"""
Core matching engine: BOQ items -> JTS quota norms (SGA primary + SGB fallback).

Seven-dimension scoring:
  1. Keyword match (+30/hit)
  2. Chapter match (+15)
  3. Unit match (+30 exact, +20 compatible, -30 type mismatch, -100 hard mismatch)
  4. Cost-item consistency (+40 hit, -50 miss)  -- prevents "现浇砼" matching pure rebar
  5. Work-content matching (+20)               -- process verb overlap
  6. Attribute hierarchy matching (+10)         -- spec/grade match with attr_levels
  7. Exclusion rules (-50/exclude, -30 manual labor penalty)

Architecture:
  SingleDBMatcher: matches against one database (SGA or SGB)
  MultiDBMatcher:  SGA primary + SGB fallback when SGA score < fallback_threshold
"""

import json, re, sqlite3
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════

@dataclass
class QuotaCandidate:
    quota_code: str
    quota_name: str
    quota_unit_raw: str
    phys_unit: str
    factor: float
    chapter_id: int
    chapter_title: str
    score: float
    score_breakdown: dict = field(default_factory=dict)
    is_manual: bool = False
    db_source: str = 'sga'
    match_evidence: str = ''


@dataclass
class MatchResult:
    row: int
    boq_name: str
    boq_description: str
    boq_unit: str
    boq_quantity: float
    context_div: str
    context_subdiv: str
    context_subitem: str
    match_type: str
    matches: list = field(default_factory=list)
    category_note: str = ''


# ═══════════════════════════════════════════════════════════
# Config loading
# ═══════════════════════════════════════════════════════════

def _resolve(path, base_dir):
    p = Path(path)
    if p.is_absolute():
        return str(p)
    return str(Path(base_dir) / p)


def load_db_config(path, base_dir):
    with open(_resolve(path, base_dir), 'r', encoding='utf-8') as f:
        return json.load(f)


def load_scoring_config(path, base_dir):
    with open(_resolve(path, base_dir), 'r', encoding='utf-8') as f:
        return json.load(f)


def load_unit_config(path, base_dir):
    with open(_resolve(path, base_dir), 'r', encoding='utf-8') as f:
        raw = json.load(f)
    mapping = {}
    for canonical, variants in raw.items():
        if canonical.startswith('_'):
            continue
        for v in variants:
            mapping[v.lower()] = canonical
    return mapping


def load_category_map(path, base_dir):
    with open(_resolve(path, base_dir), 'r', encoding='utf-8') as f:
        raw = json.load(f)
    categories = raw.get('categories', [])
    index = {}
    for cat in categories:
        keys = [cat['english_key']] + cat.get('aliases', [])
        for k in keys:
            index[k.lower()] = cat
    return categories, index


# ═══════════════════════════════════════════════════════════
# Unit helpers
# ═══════════════════════════════════════════════════════════

def normalize_unit(raw, unit_map):
    if not raw:
        return ''
    u = raw.strip().lower()
    u = re.sub(r'\s+', ' ', u)
    return unit_map.get(u, u)


def extract_quota_unit(unit_raw, db_section):
    if not unit_raw:
        return '', 1.0, ''

    raw = unit_raw.strip()
    ue = db_section.get('unit_extraction', {})

    match_re = ue.get('match_number_plus_letters',
                      r'([\d.]+)\s*([a-zA-Z²³¹⁰⁴⁵⁶⁷⁸⁹0-9]+)')
    m = re.search(match_re, raw)
    if m:
        num = float(m.group(1))
        unit_letters = m.group(2)
        unit_str = f'{m.group(1)}{unit_letters}'
        strip_num = ue.get('strip_leading_number', r'^[\d.]+')
        phys = re.sub(strip_num, '', unit_str).strip()
        strip_cn = ue.get('strip_trailing_chinese', r'[一-鿿㐀-䶿].*$')
        phys = re.sub(strip_cn, '', phys).strip()
        return unit_str, num, phys

    fallback = ue.get('fallback_chinese_unit', r'([一-鿿]+)\s*$')
    m2 = re.search(fallback, raw)
    if m2:
        return m2.group(1).strip(), 1.0, m2.group(1).strip()

    return raw, 1.0, raw


# ═══════════════════════════════════════════════════════════
# Phase 0 pre-filters
# ═══════════════════════════════════════════════════════════

# Units that map to the canonical "项" (conceptual/lump-sum) — skip matching
_CONCEPTUAL_CANONICAL_UNITS = {'项'}

# BOQ hierarchy markers that indicate a title/header row, not a work item
_TITLE_MARKER_PAIRS = [('{', '}'), ('《', '》'), ('【', '】')]


def is_conceptual_unit(unit, unit_map):
    """True if the BOQ unit is conceptual (LS/lot/项/lump sum) not physical."""
    if not unit:
        return True
    normalized = normalize_unit(unit, unit_map)
    return normalized in _CONCEPTUAL_CANONICAL_UNITS


def has_title_markers(name):
    """True if the item name contains BOQ hierarchy markers (title/header row)."""
    if not name:
        return False
    name = name.strip()
    for open_marker, close_marker in _TITLE_MARKER_PAIRS:
        if open_marker in name and close_marker in name:
            return True
    return False


# ═══════════════════════════════════════════════════════════
# Category matching
# ═══════════════════════════════════════════════════════════

def find_category(boq_name, category_index):
    name_lower = boq_name.lower().strip()
    matches = []
    for key, cat in category_index.items():
        pos = name_lower.find(key)
        if pos >= 0:
            matches.append((len(key), pos, key, cat))
    if not matches:
        return None
    matches.sort(key=lambda x: (-x[0], x[1]))
    return matches[0][3]


def is_no_match_category(cat):
    if not cat:
        return True
    return (not cat.get('target_chapters') and not cat.get('keywords'))


# ═══════════════════════════════════════════════════════════
# Material requirements for cost-item consistency analysis
# ═══════════════════════════════════════════════════════════

MATERIAL_REQUIREMENTS = [
    {
        'name': 'concrete',
        'boq_indicators': ['砼', '混凝土', 'concrete'],
        'required_cost_items': [
            '混凝土', '水泥', '砂', '石', '碎石', '卵石', '砾石',
            '外加剂', '掺合料', '粉煤灰', '矿粉',
        ],
        'score_hit': 40,
        'score_miss': -50,
        'evidence_label': '砼',
    },
    {
        'name': 'rebar',
        'boq_indicators': ['钢筋', 'rebar', 'reinforcement', 'steel bar',
                           'reinforcing steel', 'steel reinforcement'],
        'required_cost_items': [
            '钢筋', '钢丝', '型钢', '圆钢', '螺纹钢', '预应力钢筋',
            '钢绞线', '铁丝', '低碳钢',
        ],
        'score_hit': 40,
        'score_miss': -50,
        'evidence_label': '钢筋',
    },
    {
        'name': 'formwork',
        'boq_indicators': ['模板', 'formwork', 'shuttering', '支模', '拆模'],
        'required_cost_items': [
            '模板', '木', '板材', '钢模', '胶合板', '组合钢模板',
        ],
        'score_hit': 20,
        'score_miss': -30,
        'evidence_label': '模板',
    },
    {
        'name': 'steel_structure',
        'boq_indicators': ['钢结构', 'steel structure', 'steel member',
                           'steelwork', 'structural steel'],
        'required_cost_items': [
            '型钢', '钢板', '钢管', '钢材', 'H型钢', '工字钢',
            '槽钢', '角钢', '钢梁', '钢柱',
        ],
        'score_hit': 30,
        'score_miss': -40,
        'evidence_label': '钢结构',
    },
]


def analyze_cost_item_consistency(boq_text, cand_cost_items_str, weights):
    """Check if BOQ-implied materials appear in quota cost_item list.

    Returns (score_delta, evidence_parts).
    """
    score_delta = 0
    evidence_parts = []

    if not cand_cost_items_str:
        return 0, []

    cost_items_lower = cand_cost_items_str.lower()

    for req in MATERIAL_REQUIREMENTS:
        boq_has_material = any(ind in boq_text for ind in req['boq_indicators'])
        if not boq_has_material:
            continue

        quota_has_material = any(
            ci in cost_items_lower for ci in req['required_cost_items']
        )

        w_key = f'cost_item_{req["name"]}_hit'
        w_miss_key = f'cost_item_{req["name"]}_miss'
        hit_score = weights.get(w_key, req['score_hit'])
        miss_score = weights.get(w_miss_key, req['score_miss'])

        if quota_has_material:
            score_delta += hit_score
            evidence_parts.append(f'人材机含{req["evidence_label"]}(+{hit_score})')
        else:
            score_delta += miss_score
            evidence_parts.append(f'人材机缺{req["evidence_label"]}({miss_score})')

    return score_delta, evidence_parts


# ═══════════════════════════════════════════════════════════
# Work content matching (process verb overlap)
# ═══════════════════════════════════════════════════════════

PROCESS_VERBS = [
    '浇筑', '振捣', '养护', '安装', '制作', '运输', '打设', '沉桩',
    '开挖', '回填', '压实', '平整', '切割', '焊接', '涂装', '除锈',
    '吊装', '预制', '现浇', '搅拌', '摊铺', '碾压', '钻孔', '灌浆',
    '打入', '锤击', '静压', '埋设', '铺设', '砌筑', '抹面', '喷涂',
    '灌注', '振冲', '夯实', '挖土', '填土', '抛填', '吹填', '振密',
    '排水', '固结', '插打', '接桩', '送桩', '拔桩', '截桩',
    '拌和', '输送', '泵送', '振实', '整平', '凿毛', '压浆',
    '抛石', '理坡', '理砌', '护面', '护底', '垫层',
    '安放', '吊放', '沉放', '浮运', '拖运', '系泊',
    '张拉', '锚固', '封锚', '压浆', '穿束',
    '除锈', '刷漆', '喷涂', '镀锌', '防腐',
    '垫层', '找平', '抹灰', '勾缝', '嵌缝',
]


def analyze_work_content(boq_text, work_content, weights):
    """Check process verb overlap between BOQ description and quota work_content.

    Returns (score_delta, evidence_parts).
    """
    if not work_content:
        return 0, []

    matched_verbs = []
    for verb in PROCESS_VERBS:
        if verb in boq_text and verb in work_content:
            matched_verbs.append(verb)

    w = weights.get('work_content_match', 20)
    if matched_verbs:
        score = min(w, len(matched_verbs) * (w // 2))
        evidence = f'工序匹配[{ "+".join(matched_verbs[:4])}](+{score})'
        return score, [evidence]

    return 0, []


# ═══════════════════════════════════════════════════════════
# Attribute hierarchy matching
# ═══════════════════════════════════════════════════════════

def analyze_attribute_match(boq_text, attr_text, weights):
    """Check if BOQ spec details (grades, dimensions) match attr_level fields.

    Returns (score_delta, evidence_parts).
    """
    if not attr_text:
        return 0, []

    # Extract spec patterns from BOQ
    specs = set()
    # Grade: C40, C50, M30, etc.
    for m in re.finditer(r'[CM]\d{2,3}', boq_text):
        specs.add(m.group())
    # Dimensions: 800mm, 1000x1000, DN200, etc.
    for m in re.finditer(r'\d{2,4}\s*(?:mm|cm|m|直径|厚|宽|高|深)', boq_text):
        specs.add(m.group().replace(' ', ''))

    if not specs:
        return 0, []

    matched = [s for s in specs if s in attr_text]
    w = weights.get('attribute_match', 10)
    if matched:
        score = min(w, len(matched) * (w // 2))
        evidence = f'属性匹配[{",".join(matched[:3])}](+{score})'
        return score, [evidence]

    return 0, []


# ═══════════════════════════════════════════════════════════
# Match evidence builder
# ═══════════════════════════════════════════════════════════

def build_match_evidence(breakdown, total_score):
    """Assemble human-readable match evidence string."""
    parts = []

    kw = breakdown.get('keyword_hits', 0)
    if kw:
        parts.append(f'关键词命中{kw}个(+{kw * 30})')

    if breakdown.get('no_keyword_penalty'):
        parts.append('无关键词(-15)')

    exc = breakdown.get('exclude_hits', 0)
    if exc:
        parts.append(f'排除词命中{exc}个({exc * -50})')

    if breakdown.get('chapter_match'):
        parts.append('章节匹配(+15)')

    unit_type = breakdown.get('unit', 'unknown')
    if unit_type == 'exact':
        parts.append('单位一致(+30)')
    elif unit_type == 'compatible':
        parts.append('单位兼容(+20)')
    elif unit_type == 'conceptual_mismatch':
        parts.append('单位类型不匹配(-30)')
    elif unit_type == 'hard_mismatch':
        parts.append('单位不匹配(-100)')
    elif unit_type == 'no_quota_unit':
        parts.append('定额无单位(-50)')

    evidence_extra = breakdown.get('evidence_parts', [])
    parts.extend(evidence_extra)

    parts.append(f'总分{total_score:.0f}')
    return '; '.join(parts)


# ═══════════════════════════════════════════════════════════
# SingleDBMatcher: matches against one quota database
# ═══════════════════════════════════════════════════════════

class SingleDBMatcher:
    """Match BOQ items against a single quota database (SGA or SGB)."""

    def __init__(self, db_section, base_dir, scoring, unit_map,
                 categories, category_index, db_source='sga'):
        self.db_section = db_section
        self.base_dir = base_dir
        self.scoring = scoring
        self.unit_map = unit_map
        self.categories = categories
        self.category_index = category_index
        self.db_source = db_source

        self.db = sqlite3.connect(db_section['path'])
        self.db.row_factory = sqlite3.Row
        self._build_index()

    def _build_index(self):
        tc = self.db_section['tables']
        nt_cfg = tc['norms_table']['columns']
        ni_cfg = tc['norms_item']['columns']
        ch_cfg = tc['chapter']['columns']

        nt_name = tc['norms_table']['name']
        ni_name = tc['norms_item']['name']
        ch_name = tc['chapter']['name']

        self.chapter_l2_to_l1 = {}
        self.chapter_titles = {}
        for row in self.db.execute(
            f'SELECT c.{ch_cfg["id"]}, c.{ch_cfg["parent_id"]}, c.{ch_cfg["title"]} '
            f'FROM {ch_name} c WHERE c.{ch_cfg["parent_id"]} IS NOT NULL'
        ):
            l2_id = row[0]
            parent_id = row[1]
            l1_row = self.db.execute(
                f'SELECT {ch_cfg["title"]} FROM {ch_name} WHERE {ch_cfg["id"]}=?',
                (parent_id,)
            ).fetchone()
            l1_title = l1_row[0] if l1_row else ''
            self.chapter_l2_to_l1[l2_id] = l1_title
            self.chapter_titles[l2_id] = row[2] or ''

        self.index = []
        self.index_by_chapter = defaultdict(list)

        query = f'''
            SELECT
                ni.{ni_cfg["id"]},
                ni.{ni_cfg["norms_code"]},
                ni.{ni_cfg["attr_level1"]},
                ni.{ni_cfg["attr_level2"]},
                ni.{ni_cfg["attr_level3"]},
                ni.{ni_cfg["attr_level4"]},
                ni.{ni_cfg["cost_item"]},
                ni.{ni_cfg["cost_item_unit"]},
                nt.{nt_cfg["section_title"]},
                nt.{nt_cfg["subsection_title"]},
                nt.{nt_cfg["work_content"]},
                nt.{nt_cfg["unit"]},
                nt.{nt_cfg["chapter_id"]}
            FROM {ni_name} ni
            JOIN {nt_name} nt ON ni.{ni_cfg["table_id"]} = nt.{nt_cfg["id"]}
        '''

        seen_codes = set()
        for row in self.db.execute(query):
            norms_code = row[1]
            attr_vals = tuple(
                (row[i] or '').strip() if row[i] else ''
                for i in range(2, 6)
            )
            dedup_key = (norms_code, attr_vals)
            if dedup_key in seen_codes:
                continue
            seen_codes.add(dedup_key)

            attr_texts = []
            for i in range(2, 6):
                v = row[i]
                if v:
                    attr_texts.append(str(v).strip())
            attr_desc = ' '.join(attr_texts)

            section_title = row[8] or ''
            work_content = row[10] or ''
            base_name = ' '.join(filter(None, [section_title, work_content]))
            full_name = f'{base_name} [{attr_desc}]' if attr_desc else base_name
            full_name = re.sub(r'\s+', ' ', full_name).strip()

            search_corpus = full_name
            cost_item = row[6] or ''
            if cost_item:
                search_corpus += ' ' + str(cost_item).strip()

            unit_raw = row[11] or ''
            if not unit_raw:
                unit_raw_from_wc = work_content
                quota_unit_str, factor, phys_unit = extract_quota_unit(
                    unit_raw_from_wc, self.db_section)
            else:
                quota_unit_str, factor, phys_unit = extract_quota_unit(
                    unit_raw, self.db_section)
            if not phys_unit and section_title:
                _, _, phys_unit = extract_quota_unit(section_title, self.db_section)
            cost_item_unit = row[7] or ''
            if not phys_unit and cost_item_unit:
                _, _, phys_unit = extract_quota_unit(cost_item_unit, self.db_section)

            chapter_id = row[12] or 0
            l1_title = self.chapter_l2_to_l1.get(chapter_id, '')

            item = {
                'id': row[0],
                'norms_code': norms_code,
                'name': full_name,
                'search_text': search_corpus,
                'quota_unit_raw': unit_raw or quota_unit_str,
                'quota_unit_str': quota_unit_str,
                'phys_unit': phys_unit,
                'factor': factor,
                'chapter_id': chapter_id,
                'chapter_title': l1_title,
                'is_manual': '人力' in full_name,
                'work_content': work_content,
                'cost_item': str(cost_item).strip() if cost_item else '',
                'attr_desc': attr_desc,
            }
            self.index.append(item)
            self.index_by_chapter[chapter_id].append(item)
            self.index_by_chapter[l1_title].append(item)

    def match(self, name, description='', unit='', context=None, top_n=5):
        context = context or {}
        weights = self.scoring.get('weights', {})
        thresholds = self.scoring.get('thresholds', {})

        # Phase 0: Pre-filter — skip conceptual units and title/header items
        if has_title_markers(name):
            return MatchResult(
                row=0, boq_name=name, boq_description=description,
                boq_unit=unit, boq_quantity=0,
                context_div=context.get('div', ''),
                context_subdiv=context.get('subdiv', ''),
                context_subitem=context.get('subitem', ''),
                match_type='无对应定额',
                category_note='标题项(非实体工程项目)')
        if is_conceptual_unit(unit, self.unit_map):
            return MatchResult(
                row=0, boq_name=name, boq_description=description,
                boq_unit=unit, boq_quantity=0,
                context_div=context.get('div', ''),
                context_subdiv=context.get('subdiv', ''),
                context_subitem=context.get('subitem', ''),
                match_type='无对应定额',
                category_note='总价/概念类条目不套施工定额')

        # Phase 1: Context scoping
        cat = find_category(name, self.category_index)
        cat_note = cat.get('note', '') if cat else ''

        if is_no_match_category(cat):
            return MatchResult(
                row=0, boq_name=name, boq_description=description,
                boq_unit=unit, boq_quantity=0,
                context_div=context.get('div', ''),
                context_subdiv=context.get('subdiv', ''),
                context_subitem=context.get('subitem', ''),
                match_type='无对应定额',
                category_note=cat_note)

        target_chs = cat.get('target_chapters', [])
        if target_chs:
            candidates = []
            seen = {}
            for ch_title in target_chs:
                for item in self.index_by_chapter.get(ch_title, []):
                    if item['norms_code'] not in seen:
                        seen[item['norms_code']] = item
            candidates = list(seen.values())
        else:
            candidates = list(self.index)

        if not candidates:
            candidates = list(self.index)

        # Phase 2: Keyword search
        cat_kws = cat.get('keywords', [])
        cat_exc = cat.get('exclude_keywords', [])

        boq_text = f'{name} {description}'
        cn_tokens = set(re.findall(r'[一-鿿]{2,}', boq_text))

        search_kws = list(cat_kws)
        if not search_kws:
            search_kws = list(cn_tokens)

        if search_kws:
            top_n_candidates = thresholds.get('top_n_candidates', 200)
            filtered = []
            for cand in candidates:
                st = cand['search_text']
                for kw in search_kws:
                    if kw in st:
                        filtered.append(cand)
                        break
                if len(filtered) >= top_n_candidates:
                    break
            if filtered:
                candidates = filtered

        # Phase 3: Multi-factor scoring
        boq_unit_norm = normalize_unit(unit, self.unit_map)
        scored = []
        for cand in candidates:
            score = 0
            breakdown = {}
            evidence_parts = []

            # Dimension 1: Keyword hits
            kw_hits = 0
            for kw in cat_kws:
                if kw in cand['search_text']:
                    kw_hits += 1
                    score += weights.get('keyword_match', 30)
            breakdown['keyword_hits'] = kw_hits

            if not kw_hits and cat_kws:
                score += weights.get('no_keyword_penalty', -15)
                breakdown['no_keyword_penalty'] = True

            # Dimension 2: Exclude keywords
            exc_hits = 0
            for ekw in cat_exc:
                if ekw in cand['search_text']:
                    exc_hits += 1
                    score += weights.get('exclude_keyword_penalty', -50)
            breakdown['exclude_hits'] = exc_hits

            # Dimension 3: Chapter match
            if any(tc in cand['chapter_title'] for tc in target_chs):
                score += weights.get('chapter_match', 15)
                breakdown['chapter_match'] = True
            else:
                breakdown['chapter_match'] = False

            # Dimension 4: Unit scoring
            cand_unit_norm = normalize_unit(cand['phys_unit'], self.unit_map)
            breakdown['boq_unit'] = boq_unit_norm
            breakdown['cand_unit'] = cand_unit_norm

            if boq_unit_norm and cand_unit_norm:
                if boq_unit_norm == cand_unit_norm:
                    score += weights.get('unit_exact_match', 30)
                    breakdown['unit'] = 'exact'
                else:
                    compat_pairs = self.scoring.get('unit_compatibility', {}).get(
                        'compatible_pairs', [])
                    is_compat = any(
                        (boq_unit_norm == a and cand_unit_norm == b) or
                        (boq_unit_norm == b and cand_unit_norm == a)
                        for a, b in compat_pairs
                    )
                    if is_compat:
                        score += weights.get('unit_compatible_match', 20)
                        breakdown['unit'] = 'compatible'
                    else:
                        conceptual_groups = self.scoring.get('unit_compatibility', {}).get(
                            'conceptual_mismatch_groups', [])
                        boq_is_conceptual = any(
                            boq_unit_norm in g for g in conceptual_groups[:1])
                        cand_is_conceptual = any(
                            cand_unit_norm in g for g in conceptual_groups[:1])
                        if boq_is_conceptual != cand_is_conceptual:
                            score += weights.get('unit_type_mismatch', -30)
                            breakdown['unit'] = 'conceptual_mismatch'
                        else:
                            score += weights.get('unit_hard_mismatch', -100)
                            breakdown['unit'] = 'hard_mismatch'
            elif not cand['phys_unit']:
                score += weights.get('no_quota_unit_penalty', -50)
                breakdown['unit'] = 'no_quota_unit'
            else:
                breakdown['unit'] = 'unknown'

            # Dimension 5: Cost-item consistency analysis
            ci_score, ci_evidence = analyze_cost_item_consistency(
                boq_text, cand.get('cost_item', ''), weights)
            score += ci_score
            evidence_parts.extend(ci_evidence)
            breakdown['cost_item_score'] = ci_score

            # Dimension 6: Work content matching
            wc_score, wc_evidence = analyze_work_content(
                boq_text, cand.get('work_content', ''), weights)
            score += wc_score
            evidence_parts.extend(wc_evidence)
            breakdown['work_content_score'] = wc_score

            # Dimension 7: Attribute hierarchy matching
            at_score, at_evidence = analyze_attribute_match(
                boq_text, cand.get('attr_desc', ''), weights)
            score += at_score
            evidence_parts.extend(at_evidence)
            breakdown['attribute_score'] = at_score

            # Manual labor penalty for earthwork
            chapter_rules = self.scoring.get('chapter_specific_rules', {})
            earthwork_cfg = chapter_rules.get('earthwork_prefer_mechanical', {})
            if earthwork_cfg:
                earthwork_kws = earthwork_cfg.get('chapter_keywords', [])
                if cand.get('is_manual') and any(kw in cat_kws for kw in earthwork_kws):
                    penalty = earthwork_cfg.get('penalty', -30)
                    score += penalty
                    evidence_parts.append(f'人力定额惩罚({penalty})')

            breakdown['evidence_parts'] = evidence_parts
            breakdown['total'] = score
            scored.append((score, breakdown, cand))

        scored.sort(key=lambda x: -x[0])

        seen_codes = set()
        top_matches = []
        for score, breakdown, cand in scored:
            if cand['norms_code'] in seen_codes:
                continue
            seen_codes.add(cand['norms_code'])
            evidence = build_match_evidence(breakdown, score)
            top_matches.append(QuotaCandidate(
                quota_code=cand['norms_code'],
                quota_name=cand['name'],
                quota_unit_raw=cand['quota_unit_raw'],
                phys_unit=cand['phys_unit'],
                factor=cand['factor'],
                chapter_id=cand['chapter_id'],
                chapter_title=cand['chapter_title'],
                score=score,
                score_breakdown=breakdown,
                is_manual=cand.get('is_manual', False),
                db_source=self.db_source,
                match_evidence=evidence,
            ))
            if len(top_matches) >= top_n:
                break

        min_score = thresholds.get('min_score', 30)
        if not top_matches or top_matches[0].score < min_score:
            match_type = '得分不足'
        elif not top_matches[0].quota_unit_raw:
            match_type = '定额无单位'
        else:
            match_type = '已匹配'

        return MatchResult(
            row=0,
            boq_name=name,
            boq_description=description,
            boq_unit=unit,
            boq_quantity=0,
            context_div=context.get('div', ''),
            context_subdiv=context.get('subdiv', ''),
            context_subitem=context.get('subitem', ''),
            match_type=match_type,
            matches=top_matches,
            category_note=cat_note)

    def match_batch(self, items, top_n=5):
        results = []
        for i, item in enumerate(items):
            context = {
                'div': item.get('context_div', ''),
                'subdiv': item.get('context_subdiv', ''),
                'subitem': item.get('context_subitem', ''),
            }
            result = self.match(
                name=item.get('name', ''),
                description=item.get('description', ''),
                unit=item.get('unit', ''),
                context=context,
                top_n=top_n,
            )
            result.row = item.get('row', i + 1)
            result.boq_quantity = item.get('qty', 0)
            results.append(result)
        return results

    def get_chapter_tree(self):
        ch_cfg = self.db_section['tables']['chapter']['columns']
        ch_name = self.db_section['tables']['chapter']['name']
        chapters = []
        for row in self.db.execute(
            f'SELECT {ch_cfg["id"]}, {ch_cfg["parent_id"]}, '
            f'{ch_cfg["level"]}, {ch_cfg["title"]} '
            f'FROM {ch_name} ORDER BY {ch_cfg["sort_order"]}'
        ):
            chapters.append({
                'id': row[0],
                'parent_id': row[1],
                'level': row[2],
                'title': row[3] or '',
            })
        return chapters

    def get_candidate_details(self, norms_code):
        ni_cfg = self.db_section['tables']['norms_item']['columns']
        ni_name = self.db_section['tables']['norms_item']['name']
        nt_cfg = self.db_section['tables']['norms_table']['columns']
        nt_name = self.db_section['tables']['norms_table']['name']

        row = self.db.execute(
            f'SELECT ni.*, nt.{nt_cfg["section_title"]}, nt.{nt_cfg["work_content"]}, '
            f'nt.{nt_cfg["unit"]} '
            f'FROM {ni_name} ni JOIN {nt_name} nt ON ni.{ni_cfg["table_id"]}=nt.{nt_cfg["id"]} '
            f'WHERE ni.{ni_cfg["norms_code"]}=? LIMIT 1',
            (norms_code,)
        ).fetchone()
        if not row:
            return None
        return dict(row)

    def close(self):
        self.db.close()


# ═══════════════════════════════════════════════════════════
# MultiDBMatcher: SGA (primary) + SGB (fallback)
# ═══════════════════════════════════════════════════════════

class MultiDBMatcher:
    """Two-database matcher: SGA primary, SGB fallback when score < threshold."""

    def __init__(self, db_config_path, scoring_config_path=None,
                 unit_config_path=None, category_map_path=None,
                 base_dir=None):
        if base_dir is None:
            base_dir = str(Path(__file__).resolve().parent.parent)
        self.base_dir = base_dir

        self.db_config = load_db_config(db_config_path, base_dir)
        self.scoring = load_scoring_config(
            scoring_config_path or
            str(Path(base_dir) / 'config' / 'scoring_config.json'), base_dir)
        self.unit_map = load_unit_config(
            unit_config_path or
            str(Path(base_dir) / 'config' / 'unit_mapping.json'), base_dir)
        self.categories, self.category_index = load_category_map(
            category_map_path or
            str(Path(base_dir) / 'data' / 'category_map.json'), base_dir)

        db_sections = self.db_config.get('databases', {})
        match_strategy = self.db_config.get('matching_strategy', {})
        self.fallback_threshold = match_strategy.get('fallback_threshold', 30)
        self.code_separator = match_strategy.get('code_separator', '+')

        self.sga = SingleDBMatcher(
            db_sections['sga'], base_dir, self.scoring,
            self.unit_map, self.categories, self.category_index,
            db_source='sga')

        if 'sgb' in db_sections:
            self.sgb = SingleDBMatcher(
                db_sections['sgb'], base_dir, self.scoring,
                self.unit_map, self.categories, self.category_index,
                db_source='sgb')
        else:
            self.sgb = None

    def match(self, name, description='', unit='', context=None, top_n=5):
        """Match a single BOQ item against SGA (primary) + SGB (fallback).

        Strategy:
          1. Match against SGA first
          2. If best SGA score < fallback_threshold, also search SGB
          3. SGB results are prefixed with 'SGB' in code for clarity
          4. Process chain items (SGA+SGB) use + separator
        """
        result = self.sga.match(name, description, unit, context, top_n)

        if result.match_type in ('无对应定额',):
            return result

        best_sga_score = result.matches[0].score if result.matches else 0

        if best_sga_score < self.fallback_threshold and self.sgb:
            sgb_result = self.sgb.match(name, description, unit, context, top_n)
            if sgb_result.matches:
                for m in sgb_result.matches:
                    m.db_source = 'sgb'
                    # DB already stores SGB prefix (e.g. SGB61), no need to add again
                combined = result.matches + sgb_result.matches
                combined.sort(key=lambda x: -x.score)
                seen = set()
                deduped = []
                for m in combined:
                    if m.quota_code not in seen:
                        seen.add(m.quota_code)
                        deduped.append(m)
                result.matches = deduped[:top_n]
                if result.matches and result.matches[0].score >= self.scoring.get(
                        'thresholds', {}).get('min_score', 30):
                    result.match_type = '已匹配'

        # Detect process chain candidates:
        # If best single match score is mediocre (30-80) and BOQ text suggests
        # multi-step process, flag for review
        best_score = result.matches[0].score if result.matches else 0
        if 30 <= best_score < 80 and result.match_type == '已匹配':
            boq_text = f'{name} {description}'
            # If BOQ has many process verbs but match only covers some
            verbs_in_boq = [v for v in PROCESS_VERBS if v in boq_text]
            if len(verbs_in_boq) >= 3:
                wc = result.matches[0].quota_name
                verbs_covered = sum(1 for v in verbs_in_boq if v in wc)
                if verbs_covered < len(verbs_in_boq) * 0.5:
                    result.category_note = (
                        result.category_note +
                        f' [建议拆项: BOQ含{len(verbs_in_boq)}道工序, '
                        f'定额仅覆盖{verbs_covered}道]')

        return result

    def match_batch(self, items, top_n=5):
        results = []
        for i, item in enumerate(items):
            context = {
                'div': item.get('context_div', ''),
                'subdiv': item.get('context_subdiv', ''),
                'subitem': item.get('context_subitem', ''),
            }
            result = self.match(
                name=item.get('name', ''),
                description=item.get('description', ''),
                unit=item.get('unit', ''),
                context=context,
                top_n=top_n,
            )
            result.row = item.get('row', i + 1)
            result.boq_quantity = item.get('qty', 0)
            results.append(result)
        return results

    def get_candidate_details(self, norms_code):
        """Get full details for a quota code, checking SGA first then SGB."""
        if norms_code.startswith('SGB'):
            if self.sgb:
                return self.sgb.get_candidate_details(norms_code)
            return None
        return self.sga.get_candidate_details(norms_code)

    def close(self):
        self.sga.close()
        if self.sgb:
            self.sgb.close()


# Backward compatibility alias
NormsMatcher = MultiDBMatcher
