"""
同义词组、专业大类、技能归一：支持从 config/ 外置加载。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple, Union

from .utils import resolve_path

# ---------------------------------------------------------------------------
# 内置缺省（yaml 缺失时回退）
# ---------------------------------------------------------------------------

DEFAULT_SYNONYM_GROUPS = [
    {"ai", "人工智能", "artificial intelligence"},
    {"cv", "计算机视觉", "computer vision"},
    {"nlp", "自然语言处理", "natural language processing"},
    {"ml", "机器学习", "machine learning"},
    {"data", "数据分析", "数据科学", "data science", "统计科学"},
    {"web", "前端", "后端", "全栈", "web开发"},
    {"算法竞赛", "算法编程", "算法", "acm", "acm赛制", "编程"},
    {"数学建模", "数学竞赛", "建模"},
    {"计算机", "计算机能力", "计算机素养", "cs"},
    {"博弈", "计算机博弈"},
    {"英语", "商务英语", "外交英语", "英语竞赛", "翻译"},
]

DEFAULT_MAJOR_GROUPS = {
    "工学": [
        "计算机", "软件", "电子", "通信", "自动化", "电气",
        "机械", "土木", "化工", "材料", "环境", "生物医学",
    ],
    "理学": ["数学", "物理", "化学", "生物", "地理", "统计", "心理"],
    "管理学": ["管理", "工商", "会计", "财务", "市场", "人力", "物流", "工程管理"],
    "经济学": ["经济", "金融", "国贸", "财政", "保险"],
    "文学": ["中文", "外语", "新闻", "广告", "汉语言"],
}

DEFAULT_SKILL_NORMALIZE = {
    "数学基础理论": "数学建模",
    "建模方法原理": "数学建模",
    "数学建模": "数学建模",
    "计算机组成原理": "计算机",
    "计算机网络": "计算机",
    "算法编程": "算法",
    "python": "编程",
    "java": "编程",
    "c++": "编程",
    "c语言": "编程",
}

PROGRAMMING_HINTS = {"python", "java", "c++", "c语言", "编程", "程序", "算法"}


def _load_yaml(path_value: str) -> dict:
    path = resolve_path(path_value)
    if not path.exists():
        return {}
    try:
        import yaml

        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_lexicon(rec_cfg: Optional[dict] = None) -> dict:
    """加载同义词 / 专业大类 / 技能归一表。

    Returns:
        {
          synonym_groups: list[set],
          major_groups: dict,
          skill_normalize: dict,
        }
    """
    rec_cfg = rec_cfg if isinstance(rec_cfg, dict) else {}
    syn_path = rec_cfg.get(
        "synonyms_path", "./config/recommendation_synonyms.yaml"
    )
    maj_path = rec_cfg.get(
        "majors_path", "./config/recommendation_majors.yaml"
    )

    syn_data = _load_yaml(syn_path)
    maj_data = _load_yaml(maj_path)

    groups = []
    raw_groups = syn_data.get("synonym_groups")
    if isinstance(raw_groups, list) and raw_groups:
        for g in raw_groups:
            if isinstance(g, (list, set, tuple)):
                cleaned = {str(x).strip() for x in g if str(x).strip()}
                if cleaned:
                    groups.append(cleaned)
    if not groups:
        groups = [set(g) for g in DEFAULT_SYNONYM_GROUPS]

    skill_norm = dict(DEFAULT_SKILL_NORMALIZE)
    raw_norm = syn_data.get("skill_normalize")
    if isinstance(raw_norm, dict):
        for k, v in raw_norm.items():
            if k and v:
                skill_norm[str(k).strip().lower()] = str(v).strip().lower()

    major_groups = dict(DEFAULT_MAJOR_GROUPS)
    raw_majors = maj_data.get("major_groups")
    if isinstance(raw_majors, dict) and raw_majors:
        parsed = {}
        for cat, kws in raw_majors.items():
            if isinstance(kws, list):
                parsed[str(cat)] = [str(x) for x in kws if x]
        if parsed:
            major_groups = parsed

    return {
        "synonym_groups": groups,
        "major_groups": major_groups,
        "skill_normalize": skill_norm,
    }


def normalize_skill(skill: str, skill_normalize: Optional[dict] = None) -> str:
    """将细技能映射到领域词。"""
    text = (skill or "").strip().lower()
    if not text:
        return ""
    mapping = skill_normalize or DEFAULT_SKILL_NORMALIZE
    # 键已存小写
    if text in mapping:
        return mapping[text]
    for k, v in mapping.items():
        if k in text or text in k:
            return v
    return text


def conceptual_overlap(
    user_tags: list,
    project_tags: list,
    synonym_groups: list = None,
) -> int:
    """计算概念重合数。"""
    count, _ = conceptual_overlap_detail(user_tags, project_tags, synonym_groups)
    return count


def conceptual_overlap_detail(
    user_tags: list,
    project_tags: list,
    synonym_groups: list = None,
) -> Tuple[int, List[str]]:
    """返回 (重合数, 命中描述列表)。"""

    def _normalize(tag: str) -> str:
        return tag.strip().lower()

    groups = synonym_groups if synonym_groups is not None else DEFAULT_SYNONYM_GROUPS
    user_set = {_normalize(t) for t in user_tags if t}
    proj_set = {_normalize(t) for t in project_tags if t}
    if not user_set or not proj_set:
        return 0, []

    matched_user: Set[str] = set()
    matched_proj: Set[str] = set()
    signals: List[str] = []
    group_matches = 0

    for group in groups:
        group_lower = {_normalize(g) for g in group}
        user_hit = user_set & group_lower
        proj_hit = proj_set & group_lower
        if user_hit and proj_hit:
            group_matches += 1
            matched_user |= user_hit
            matched_proj |= proj_hit
            u = next(iter(user_hit))
            p = next(iter(proj_hit))
            signals.append(f"兴趣:{u}<->{p}")

    direct = (user_set - matched_user) & (proj_set - matched_proj)
    for d in direct:
        signals.append(f"兴趣:{d}")
        matched_user.add(d)
        matched_proj.add(d)
    direct_matches = len(direct)

    substring_matches = 0
    for ut in user_set - matched_user:
        for pt in proj_set - matched_proj:
            if len(ut) >= 2 and len(pt) >= 2 and (ut in pt or pt in ut):
                substring_matches += 1
                matched_user.add(ut)
                matched_proj.add(pt)
                signals.append(f"兴趣:{ut}<->{pt}")
                break

    return group_matches + direct_matches + substring_matches, signals


def user_ability_corpus(user: dict) -> str:
    """汇总技能、竞赛/科研经历、获奖名称，供能力匹配检索。"""
    parts = []
    for skill in user.get("skills") or []:
        parts.append(str(skill))
    for exp in user.get("competition_experience") or []:
        parts.append(str(exp))
    for exp in user.get("research_experience") or []:
        parts.append(str(exp))
    for award in user.get("awards") or []:
        if isinstance(award, dict):
            parts.append(str(award.get("competition_name", "")))
            parts.append(str(award.get("award_name", "")))
        else:
            parts.append(str(award))
    return " ".join(parts).lower()


def skill_matches(
    user_skills: set,
    required_skill: str,
    corpus: str = "",
    skill_normalize: Optional[dict] = None,
) -> bool:
    """判断用户是否满足单项 required_skill（含领域归一）。"""
    req = required_skill.strip().lower()
    if not req:
        return False
    req_norm = normalize_skill(req, skill_normalize)
    for skill in user_skills:
        s = skill if isinstance(skill, str) else str(skill)
        s_norm = normalize_skill(s, skill_normalize)
        if (
            s == req
            or s in req
            or req in s
            or s_norm == req_norm
            or (s_norm and req_norm and (s_norm in req_norm or req_norm in s_norm))
        ):
            return True
    if len(req) >= 2 and req in corpus:
        return True
    if req_norm and len(req_norm) >= 2 and req_norm in corpus:
        return True
    if any(h in req for h in ("编程", "程序", "计算机技术")):
        return bool(user_skills & PROGRAMMING_HINTS)
    return False


def count_skill_overlap(
    user_skills: set,
    required: list,
    corpus: str = "",
    skill_normalize: Optional[dict] = None,
) -> Tuple[int, int, List[str], List[str]]:
    """返回 (匹配数, 要求总数, 命中技能, 未命中技能)。"""
    if not required:
        return 0, 0, [], []
    matched_list = []
    unmatched_list = []
    for r in required:
        if skill_matches(user_skills, r, corpus, skill_normalize):
            matched_list.append(str(r))
        else:
            unmatched_list.append(str(r))
    return len(matched_list), len(required), matched_list, unmatched_list
