"""
推荐匹配 Agent (RecommendationAgent)

负责根据用户画像（专业、年级、兴趣、能力、时间、团队状态）与结构化项目数据
进行多维度匹配，输出 Top-N 推荐结果及推荐理由。

依赖:
    - 输入 structured_items 来自 InfoExtractAgent（成员B）
    - 输入 user_profile 来自 Main Agent（Leader）
    - 输出 recommendations[] 传递给 MaterialAgent（成员D）

依据规范:
    PROJECT_SPEC_CN.md 第 12.3 节 — RecommendationAgent
"""

from datetime import datetime, date
import re


# ---------------------------------------------------------------------------
# 常量定义
# ---------------------------------------------------------------------------

# 推荐维度默认权重（可通过 config.yaml 或 recommendation_rules 覆盖）
# 真实竞赛数据：专业/年级限制少；兴趣、能力、团队、截止更有区分度
# 权重以 config.yaml 的 recommendation.weights 为准，此处仅作缺省回退
_DEFAULT_WEIGHTS = {
    "interest_score":      0.30,
    "ability_score":       0.25,
    "deadline_score":      0.18,
    "team_score":          0.12,
    "grade_score":         0.10,
    "major_score":         0.05,
}

# 权重维度顺序（综合分计算与归一化共用）
_WEIGHT_KEYS = tuple(_DEFAULT_WEIGHTS.keys())

# deadline 解析哨兵：表示日期未知（区别于已过期或解析失败）
_DEADLINE_UNKNOWN = -999998

# 硬性门槛：专业匹配低于此分视为不符合（target_majors 非空时）
_HARD_MAJOR_MIN_SCORE = 50

# 推荐等级划分阈值（适配真实数据得分分布，略低于 7.8 文档初版）
_LEVEL_THRESHOLDS = [
    (80, "S", "强烈推荐"),
    (65, "A", "推荐"),
    (50, "B", "可考虑"),
    (0,  "C", "不推荐"),
]

# 维度中文名（用于 reason / risk / action 文案）
_DIM_NAME_MAP = {
    "major_score":    "专业匹配度",
    "grade_score":    "年级/学历匹配度",
    "interest_score": "兴趣匹配度",
    "ability_score":  "能力匹配度",
    "deadline_score": "截止时间可行性",
    "team_score":     "团队匹配度",
}

# 推荐文案使用的维度（专业/年级多数竞赛不限，不作为 reason/risk/action 的主要依据）
_COPY_DIM_KEYS = (
    "interest_score",
    "ability_score",
    "deadline_score",
    "team_score",
)

# 等级排序（用于封顶规则）
_LEVEL_ORDER = {"S": 4, "A": 3, "B": 2, "C": 1}

# 兴趣标签同义词组（勿把「计算机」并入 AI，否则兴趣=人工智能会误匹配所有 CS 赛）
_SYNONYM_GROUPS = [
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

# 能力技能弱匹配关键词（成员B的 required_skills 表述较细，需子串/编程类归一）
_PROGRAMMING_HINTS = {"python", "java", "c++", "c语言", "编程", "程序", "算法"}

def _safe_int(value, default: int = 0) -> int:
    """将入学年份等字段安全转为 int。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _enrollment_to_grade(enrollment_year, today: date = None) -> str:
    """根据入学年份推断当前年级文字描述。

    使用实时日期计算，而非硬编码年份月份。
    业务规则：每年 9 月开学后年级自动进阶。
    """
    year = _safe_int(enrollment_year, 0)
    if year <= 0:
        return "未知"
    if today is None:
        today = date.today()
    # 例：2024 年 9 月入学 → 2024-09~2025-08 为大一
    academic_years = today.year - year
    if today.month < 9:
        academic_years -= 1
    grade_index = academic_years + 1  # 1=大一
    if grade_index <= 1:
        return "大一"
    if grade_index == 2:
        return "大二"
    if grade_index == 3:
        return "大三"
    if grade_index == 4:
        return "大四"
    return f"大{grade_index}及以上"


def _grade_to_min_year(target_grades: list, today: date = None) -> int:
    """将目标年级列表转换为「满足最低年级要求」的最晚入学年份。

    例：要求大三及以上、今天 2026-07 → 最晚入学年约为 2023。
    """
    if not target_grades:
        return 9999  # 无限制
    if today is None:
        today = date.today()
    grade_map = {"大一": 1, "大二": 2, "大三": 3, "大四": 4, "大五": 5}
    min_grade = 5
    found = False
    for g in target_grades:
        key = str(g).strip()
        if key in grade_map:
            min_grade = min(min_grade, grade_map[key])
            found = True
    if not found:
        return 9999
    # grade_index = today.year - enroll + (1 if month>=9 else 0)
    # 要求 grade_index >= min_grade => enroll <= today.year + offset - min_grade
    offset = 1 if today.month >= 9 else 0
    return today.year + offset - min_grade


def _conceptual_overlap(user_tags: list, project_tags: list) -> int:
    """计算用户与项目标签的概念重合数（同义词组只计 1 次）。

    避免 "AI" 与 "人工智能" 因同义词扩展被重复计为多个重合。
    """
    def _normalize(tag: str) -> str:
        return tag.strip().lower()

    user_set = {_normalize(t) for t in user_tags if t}
    proj_set = {_normalize(t) for t in project_tags if t}
    if not user_set or not proj_set:
        return 0

    matched_user = set()
    matched_proj = set()
    group_matches = 0

    for group in _SYNONYM_GROUPS:
        group_lower = {_normalize(g) for g in group}
        user_hit = user_set & group_lower
        proj_hit = proj_set & group_lower
        if user_hit and proj_hit:
            group_matches += 1
            matched_user |= user_hit
            matched_proj |= proj_hit

    direct_matches = len((user_set - matched_user) & (proj_set - matched_proj))

    # 子串弱匹配：如「算法竞赛」与「算法编程」共享「算法」
    substring_matches = 0
    for ut in user_set - matched_user:
        for pt in proj_set - matched_proj:
            if len(ut) >= 2 and len(pt) >= 2 and (ut in pt or pt in ut):
                substring_matches += 1
                matched_user.add(ut)
                matched_proj.add(pt)
                break

    return group_matches + direct_matches + substring_matches


def _days_until_deadline(deadline_str: str, today: date = None) -> int:
    """解析截止日期字符串，计算距离今天的天数。

    支持格式：2026-08-15 或 2026/08/15 或 2026.08.15

    Returns:
        天数差；unknown/空 返回 _DEADLINE_UNKNOWN；其他解析失败返回 99999
    """
    if today is None:
        today = date.today()
    if not deadline_str or deadline_str.strip().lower() == "unknown":
        return _DEADLINE_UNKNOWN
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            dt = datetime.strptime(deadline_str.strip(), fmt).date()
            return (dt - today).days
        except ValueError:
            continue
    return 99999


def _user_ability_corpus(user: dict) -> str:
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


def _skill_matches(user_skills: set, required_skill: str, corpus: str = "") -> bool:
    """判断用户是否满足单项 required_skill（技能标签 / 经历文本 / 编程弱匹配）。"""
    req = required_skill.strip().lower()
    if not req:
        return False
    for skill in user_skills:
        if skill == req or skill in req or req in skill:
            return True
    # 竞赛/科研经历中出现该技能关键词（如经历含「数学建模」）
    if len(req) >= 2 and req in corpus:
        return True
    if any(h in req for h in ("编程", "程序", "计算机技术")):
        return bool(user_skills & _PROGRAMMING_HINTS)
    return False


def _count_skill_overlap(user_skills: set, required: list, corpus: str = "") -> tuple:
    """返回 (匹配数, 要求总数)。"""
    if not required:
        return 0, 0
    matched = sum(1 for r in required if _skill_matches(user_skills, r, corpus))
    return matched, len(required)


def _parse_available_month_range(available_time: str):
    """解析 available_time 中的起止年月，失败返回 None。

    支持示例：2026年7月-9月 / 2026年7月-2026年9月 / 2026-07~2026-09
    """
    if not available_time:
        return None
    text = str(available_time).strip()
    patterns = [
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*[-~—至到]+\s*(\d{4})\s*年\s*(\d{1,2})\s*月",
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*[-~—至到]+\s*(\d{1,2})\s*月",
        r"(\d{4})[-/.](\d{1,2})\s*[-~—至到]+\s*(\d{4})[-/.](\d{1,2})",
    ]
    m = re.search(patterns[0], text)
    if m:
        y1, mo1, y2, mo2 = map(int, m.groups())
        return (y1, mo1), (y2, mo2)
    m = re.search(patterns[1], text)
    if m:
        y1, mo1, mo2 = map(int, m.groups())
        return (y1, mo1), (y1, mo2)
    m = re.search(patterns[2], text)
    if m:
        y1, mo1, y2, mo2 = map(int, m.groups())
        return (y1, mo1), (y2, mo2)
    return None


def _project_root():
    """返回项目根目录（含 config/、data/、agents/ 的目录）。"""
    from pathlib import Path
    return Path(__file__).resolve().parents[1]


def _resolve_path(path_value: str):
    """将配置中的相对路径解析为基于项目根的绝对 Path（不写死盘符路径）。"""
    from pathlib import Path
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (_project_root() / path).resolve()


def _load_config(config_path: str = None) -> dict:
    """从 config/config.yaml 加载配置；失败时返回空 dict，不中断进程。"""
    from pathlib import Path

    path = _resolve_path(config_path) if config_path else _project_root() / "config" / "config.yaml"
    if not path.exists():
        return {}
    try:
        import yaml
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_json_file(filepath) -> dict:
    """读取 JSON 文件；不存在或解析失败时返回空 dict。"""
    import json
    from pathlib import Path

    path = Path(filepath)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def build_sample_input(config: dict = None, sample_path: str = None) -> dict:
    """从项目 data/processed 下的标准样例组装 RecommendationAgent 输入。

    样例路径优先顺序：
    1. 显式传入 sample_path
    2. config.recommendation.sample_input_path
    3. 默认 ./data/processed/recommendation_input_sample.json
    """
    cfg = config or {}
    rec_cfg = cfg.get("recommendation", {}) if isinstance(cfg, dict) else {}
    default_path = "./data/processed/recommendation_input_sample.json"
    path_value = sample_path or (
        rec_cfg.get("sample_input_path", default_path) if isinstance(rec_cfg, dict) else default_path
    )
    path = _resolve_path(path_value)
    payload = _load_json_file(path)
    if not payload:
        return {
            "task_id": "",
            "user_input": "",
            "task_type": "recommendation",
            "user_profile": {},
            "context": {},
            "input_data": {},
            "history": [],
            "required_output": "markdown",
            "metadata": {
                "sample_path": str(path),
                "load_error": "sample_input_not_found_or_invalid",
            },
        }
    return payload


# 兼容旧联调入口名称（已改为项目内标准样例，不再读取项目外中文路径）
def build_input_from_integration_files(*_args, **kwargs) -> dict:
    """兼容旧函数名，转发到 build_sample_input。"""
    return build_sample_input(
        config=kwargs.get("config"),
        sample_path=kwargs.get("sample_path") or kwargs.get("leader_path"),
    )


# ---------------------------------------------------------------------------
# RecommendationAgent
# ---------------------------------------------------------------------------

class RecommendationAgent:
    """推荐匹配 Agent。

    对外唯一接口为 run()，输入/输出均为 dict 且符合 PROJECT_SPEC 统一规范。

    Attributes:
        config: 全局配置字典，来自 config/config.yaml
        weights: 当前生效的推荐维度权重
    """

    # ---- Agent 元信息 ----
    AGENT_NAME = "recommendation_agent"

    def __init__(self, config: dict = None):
        """初始化 Agent，加载配置和默认权重。

        Args:
            config: 全局配置字典，包含模型、API、Agent 参数等
        """
        self.config = config or {}
        rec_cfg = self.config.get("recommendation", {})
        if not isinstance(rec_cfg, dict):
            rec_cfg = {}
        self.weights = self._load_base_weights()
        self.level_thresholds = self._load_level_thresholds()
        self.hard_constraints_enabled = rec_cfg.get("hard_constraints", True)
        self.hard_major_min_score = rec_cfg.get("hard_major_min_score", _HARD_MAJOR_MIN_SCORE)
        self.level_caps = {
            "grade_score_below": 40,
            "ability_score_below": 30,
            "max_level": "B",
            **(rec_cfg.get("caps") if isinstance(rec_cfg.get("caps"), dict) else {}),
        }

    def _load_level_thresholds(self) -> list:
        """从默认阈值 + config.yaml 加载等级划分（按分数从高到低排序）。"""
        thresholds = list(_LEVEL_THRESHOLDS)
        rec_cfg = self.config.get("recommendation", {})
        if not isinstance(rec_cfg, dict):
            return sorted(thresholds, key=lambda x: x[0], reverse=True)
        custom = rec_cfg.get("level_thresholds", {})
        if not isinstance(custom, dict):
            return sorted(thresholds, key=lambda x: x[0], reverse=True)
        labels = {"S": "强烈推荐", "A": "推荐", "B": "可考虑", "C": "不推荐"}
        order = ["S", "A", "B", "C"]
        if all(k in custom for k in order):
            thresholds = [(float(custom[code]), code, labels[code]) for code in order]
        return sorted(thresholds, key=lambda x: x[0], reverse=True)

    @staticmethod
    def _normalize_weights(weights: dict) -> dict:
        """归一化权重，避免总和不为 1 时综合分整体偏高/偏低。"""
        cleaned = {}
        for key in _WEIGHT_KEYS:
            try:
                cleaned[key] = float(weights.get(key, _DEFAULT_WEIGHTS[key]))
            except (TypeError, ValueError):
                cleaned[key] = float(_DEFAULT_WEIGHTS[key])
            if cleaned[key] < 0:
                cleaned[key] = 0.0
        total = sum(cleaned.values())
        if total <= 0:
            return dict(_DEFAULT_WEIGHTS)
        return {k: v / total for k, v in cleaned.items()}

    def _load_base_weights(self) -> dict:
        """从默认权重 + config.yaml 加载并归一化基础权重。"""
        weights = dict(_DEFAULT_WEIGHTS)
        rec_cfg = self.config.get("recommendation", {})
        if isinstance(rec_cfg, dict):
            custom = rec_cfg.get("weights", {})
            if isinstance(custom, dict):
                weights.update(custom)
        return self._normalize_weights(weights)

    def _resolve_weights(self, rules: dict) -> dict:
        """合并单次请求中的权重覆盖并归一化，不修改 self.weights。"""
        weights = dict(self.weights)
        custom = rules.get("weights", {})
        if isinstance(custom, dict):
            weights.update(custom)
        return self._normalize_weights(weights)

    def _level_label(self, level_code: str) -> str:
        """根据等级代码返回中文描述。"""
        for _, code, label in self.level_thresholds:
            if code == level_code:
                return label
        return "不推荐"

    def _apply_level_cap(self, level_code: str, detail: dict, caps: dict) -> str:
        """年级或能力明显不足时封顶推荐等级（如最高 B）。"""
        max_level = caps.get("max_level", "B")
        grade_threshold = caps.get("grade_score_below", 40)
        ability_threshold = caps.get("ability_score_below", 30)
        should_cap = (
            detail.get("grade_score", 100) < grade_threshold
            or detail.get("ability_score", 100) < ability_threshold
        )
        if should_cap and _LEVEL_ORDER.get(level_code, 0) > _LEVEL_ORDER.get(max_level, 0):
            return max_level
        return level_code

    # ==================================================================
    # 统一外部接口（必须实现）
    # ==================================================================

    def run(self, input_data: dict) -> dict:
        """推荐匹配统一入口，遵循 PROJECT_SPEC 规范。

        输入格式：
        {
            "task_id": str,           # 任务编号
            "user_input": str,        # 用户原始输入
            "task_type": str,         # 任务类型
            "user_profile": dict,     # 用户画像（13个字段）
            "context": dict,          # 上下文（含其他Agent结果）
            "input_data": {           # 本Agent业务数据
                "structured_items": [ # 来自InfoExtractAgent的结构化项目列表
                    {
                        "title": str,
                        "type": str,
                        "deadline": str,
                        "registration_time": str,
                        "requirements": {
                            "target_majors": [],
                            "target_grades": [],
                            "target_education": [],
                            "required_skills": [],
                            "team_requirement": "",
                            "tags": [],
                            "category": ""
                        },
                        "reward": str,
                        "organizer": str,
                        "source_url": str,
                        "summary": str
                    }
                ],
                "user_profile": dict,       # 也可在此传入用户画像
                "recommendation_rules": {   # 可选，覆盖默认权重
                    "weights": {},
                    "top_n": 3
                }
            },
            "history": list,
            "required_output": str,
            "metadata": dict
        }

        输出格式：
        {
            "task_id": str,
            "agent_name": "recommendation_agent",
            "status": "success" | "failed" | "partial" | "need_input" | "skipped",
            "data": {
                "recommendations": [
                    {
                        "title": str,              # 项目名称
                        "match_score": float,      # 综合得分 0-100
                        "recommend_level": str,    # S/A/B/C
                        "reason": str,             # 推荐理由
                        "risk": str,               # 风险提示
                        "suggested_action": str,   # 建议行动
                        "detail": {                # 各维度明细（调试/展示用）
                            "major_score": float,
                            "grade_score": float,
                            "interest_score": float,
                            "ability_score": float,
                            "deadline_score": float,
                            "team_score": float
                        }
                    }
                ],
                "total_count": int,               # 候选项目总数
                "matched_count": int               # 生成推荐的项目数
            },
            "message": str,
            "error": None | dict,
            "next_action": None,
            "metadata": dict
        }
        """
        # 1. 参数校验
        validation_error = self.validate_input(input_data)
        if validation_error:
            return validation_error

        # 2. 核心处理
        try:
            result = self.process(input_data)
            return result
        except Exception as exc:
            # 所有异常必须在 Agent 内部捕获，返回统一错误格式
            return self._error_response(
                input_data.get("task_id", ""),
                error_type=type(exc).__name__,
                error_message=str(exc),
                suggestion="请检查输入数据格式是否正确，或联系开发者排查。",
            )

    # ==================================================================
    # 输入校验
    # ==================================================================

    def validate_input(self, input_data: dict):
        """校验输入数据是否满足推荐匹配的最低要求。

        Returns:
            None 表示校验通过；返回一个标准错误 dict 表示校验失败。
        """
        if not isinstance(input_data, dict):
            return self._error_response(
                "", "ValidationError", "input_data 必须是 dict 类型"
            )

        task_id = input_data.get("task_id", "")

        # 提取业务数据：允许扁平结构；input_data 若存在则必须是 dict
        if "input_data" in input_data and input_data["input_data"] is not None:
            business = input_data["input_data"]
            if not isinstance(business, dict):
                return self._error_response(
                    task_id,
                    "ValidationError",
                    "input_data 字段必须是 dict 类型",
                )
        else:
            business = input_data

        structured_items = business.get("structured_items", None)
        if structured_items is None:
            return self._need_input_response(
                task_id,
                "缺少结构化项目数据（structured_items），"
                "请先调用信息采集和信息抽取 Agent。",
            )
        if not isinstance(structured_items, list):
            return self._error_response(
                task_id,
                "ValidationError",
                "structured_items 必须是 list 类型",
            )
        if len(structured_items) == 0:
            return self._need_input_response(
                task_id,
                "structured_items 为空，请先补充可推荐的项目数据。",
            )

        # 校验 user_profile（可从顶层或 input_data 中取）
        user_profile = input_data.get("user_profile") or business.get("user_profile")
        if not isinstance(user_profile, dict) or not user_profile:
            return self._need_input_response(
                task_id,
                "缺少用户画像数据（user_profile），"
                "请用户完善个人信息（专业、年级、兴趣方向等）。",
            )

        return None  # 校验通过

    # ==================================================================
    # 核心推荐逻辑
    # ==================================================================

    def process(self, input_data: dict) -> dict:
        """执行六维度推荐匹配计算。

        流程：
        1. 解析输入
        2. 应用自定义权重（如有）
        3. 对每个项目计算六个维度得分
        4. 硬性门槛校验（截止/专业/年级学历不符合则排除，等效 0 分）
        5. 综合评分、按得分降序排列、划分推荐等级
        6. 取 Top-N 生成推荐文字
        7. 包装为统一输出格式
        """
        task_id = input_data.get("task_id", "")
        if "input_data" in input_data and isinstance(input_data.get("input_data"), dict):
            business = input_data["input_data"]
        else:
            business = input_data

        # ---- 解析输入 ----
        structured_items = business.get("structured_items", [])
        user_profile = input_data.get("user_profile") or business.get("user_profile", {})

        # 自定义规则（如权重覆盖）；每次请求独立合并，不污染 self.weights
        rules = business.get("recommendation_rules", {})
        if not isinstance(rules, dict):
            rules = {}
        try:
            top_n = max(1, int(rules.get("top_n", 3)))
        except (TypeError, ValueError):
            top_n = 3
        weights = self._resolve_weights(rules)
        caps = {**self.level_caps, **(rules.get("caps") if isinstance(rules.get("caps"), dict) else {})}

        # ---- 计算每个项目的匹配得分 ----
        scored = []
        hard_filtered = 0
        now = date.today()
        ability_corpus = _user_ability_corpus(user_profile)

        for item in structured_items:
            if not isinstance(item, dict):
                hard_filtered += 1
                continue

            # 获取项目 deadline
            deadline = item.get("deadline", "")
            reqs = item.get("requirements", {})
            if isinstance(reqs, dict):
                deadline = reqs.get("deadline", "") or deadline

            # 硬性门槛：不符合则直接排除（等效综合分 0，不参与排序）
            if self.hard_constraints_enabled:
                ok, _ = self._check_hard_constraints(user_profile, item, deadline, now)
                if not ok:
                    hard_filtered += 1
                    continue

            # 六个维度分别打分
            scores = {
                "major_score":    self._score_major(user_profile, item),
                "grade_score":    self._score_grade(user_profile, item, now),
                "interest_score": self._score_interest(user_profile, item),
                "ability_score":  self._score_ability(user_profile, item, ability_corpus),
                "deadline_score": self._score_deadline(
                    deadline, now, user_profile.get("available_time", "")
                ),
                "team_score":     self._score_team(user_profile, item),
            }

            # 加权综合分（四舍五入保留 1 位小数）
            total = round(
                sum(scores[k] * weights.get(k, 0.0) for k in _WEIGHT_KEYS), 1
            )

            scored.append({
                "item": item,
                "total": total,
                "scores": scores,
            })

        # ---- 排序 & 划分等级 ----
        scored.sort(key=lambda x: x["total"], reverse=True)

        recommendations = []
        for entry in scored[:top_n]:
            item = entry["item"]
            total = entry["total"]
            detail = entry["scores"]

            level_code, _ = self._to_level(total)
            level_code = self._apply_level_cap(level_code, detail, caps)
            reason = self._build_reason(detail)
            risk = self._build_risk(detail)
            action = self._build_action(level_code, detail)

            recommendations.append({
                "title":            item.get("title", "未知项目"),
                "match_score":      total,
                "recommend_level":  level_code,
                "reason":           reason,
                "risk":             risk,
                "suggested_action": action,
                "detail":           detail,
                "source_url":       item.get("source_url", ""),
                "summary":          item.get("summary", ""),
                "deadline":         item.get("deadline", ""),
                "organizer":        item.get("organizer", ""),
                "type":             item.get("type", ""),
            })

        status = "success" if recommendations else "partial"
        message = (
            f"推荐完成：共 {len(structured_items)} 个候选，"
            f"硬性不符合 {hard_filtered} 个，"
            f"有效匹配 {len(scored)} 个，返回 Top-{len(recommendations)}。"
        )
        if not recommendations:
            message = (
                f"无可用推荐：共 {len(structured_items)} 个候选，"
                f"硬性不符合 {hard_filtered} 个。"
            )

        # ---- 包装为统一输出格式 ----
        response = self._success_response(
            task_id,
            data={
                "recommendations": recommendations,
                "total_count": len(structured_items),
                "matched_count": len(scored),
                "hard_filtered_count": hard_filtered,
            },
            message=message,
        )
        response["status"] = status
        return response

    def _check_hard_constraints(self, user: dict, item: dict,
                                 deadline: str, today: date) -> tuple:
        """硬性门槛校验：截止/专业/年级/学历任一明确不符合则不得推荐。

        Returns:
            (是否通过, 拒绝原因)
        """
        days = _days_until_deadline(deadline, today)
        if days != _DEADLINE_UNKNOWN and days < 0:
            return False, "已超过报名截止时间"

        reqs = item.get("requirements", {})
        if not isinstance(reqs, dict):
            return True, ""

        target_majors = reqs.get("target_majors", [])
        if target_majors:
            if self._score_major(user, item) < self.hard_major_min_score:
                return False, "专业不在面向范围内"

        target_edu = reqs.get("target_education", [])
        education = (user.get("education_level") or "").strip()
        if target_edu:
            # 空字符串会使 `"" in "本科"` 为 True，必须先排除
            if not education:
                return False, "缺少学历信息，无法核验项目学历要求"
            edu_match = any(
                education in e or e in education for e in target_edu
            )
            if not edu_match:
                return False, "学历层次不符合要求"

        target_grades = reqs.get("target_grades", [])
        if target_grades:
            user_grade = _enrollment_to_grade(user.get("enrollment_year", 0), today)
            grade_match = any(str(g).strip() == user_grade for g in target_grades)
            if not grade_match:
                return False, "年级不符合要求"

        return True, ""

    # ==================================================================
    # 六个维度评分函数
    # ==================================================================

    def _score_major(self, user: dict, item: dict) -> float:
        """维度一：专业匹配度（默认权重见 config.yaml / _DEFAULT_WEIGHTS）。

        用户 major 与项目 target_majors 比较。
        支持模糊匹配（如 "计算机科学与技术" 匹配 "计算机类"）。
        """
        user_major = (user.get("major") or "").strip()
        reqs = item.get("requirements", {})
        if not isinstance(reqs, dict):
            return self._default_if_missing("专业匹配", user_major, 70.0)

        targets = reqs.get("target_majors", [])
        if not targets:
            return 90.0  # 不限专业

        user_lower = user_major.lower()
        for t in targets:
            t_lower = t.strip().lower()
            # 完全一致
            if user_lower == t_lower:
                return 100.0
            # 包含关系：如 "计算机" in "计算机科学与技术"
            if t_lower in user_lower or user_lower in t_lower:
                return 85.0

        # 大类映射
        major_groups = {
            "工学": ["计算机", "软件", "电子", "通信", "自动化", "电气", "机械", "土木", "化工", "材料", "环境", "生物医学"],
            "理学": ["数学", "物理", "化学", "生物", "地理", "统计", "心理"],
            "管理学": ["管理", "工商", "会计", "财务", "市场", "人力", "物流", "工程管理"],
            "经济学": ["经济", "金融", "国贸", "财政", "保险"],
            "文学": ["中文", "外语", "新闻", "广告", "汉语言"],
        }
        user_category = None
        proj_category = None
        for cat, keywords in major_groups.items():
            for kw in keywords:
                if kw in user_lower:
                    user_category = cat
                for t in targets:
                    if kw in t.strip().lower():
                        proj_category = cat

        if user_category and user_category == proj_category:
            return 80.0

        return 30.0  # 跨学科无关联

    def _score_grade(self, user: dict, item: dict, today: date = None) -> float:
        """维度二：年级/学历匹配度（默认权重见 config.yaml / _DEFAULT_WEIGHTS）。

        用户 enrollment_year + education_level 与项目 target_grades + target_education。
        """
        if today is None:
            today = date.today()
        enrollment_year = _safe_int(user.get("enrollment_year", 0), 0)
        education = (user.get("education_level") or "").strip()

        reqs = item.get("requirements", {})
        if not isinstance(reqs, dict):
            return self._default_if_missing("年级匹配", "", 70.0)

        target_grades = reqs.get("target_grades", []) or []
        target_edu = reqs.get("target_education", []) or []

        if not target_grades and not target_edu:
            return 90.0  # 无限制

        # 仅要求学历、不限年级
        if not target_grades and target_edu:
            if not education:
                return 50.0
            edu_match = any(
                education in e or e in education
                for e in target_edu
            )
            return 100.0 if edu_match else 50.0

        user_grade = _enrollment_to_grade(enrollment_year, today)

        # 学历匹配
        edu_match = True
        if target_edu:
            if not education:
                edu_match = False
            else:
                edu_match = any(
                    education in e or e in education
                    for e in target_edu
                )

        # 年级匹配
        grade_match = any(
            str(g).strip() == user_grade for g in target_grades
        )

        if grade_match and edu_match:
            return 100.0
        if grade_match and not edu_match:
            return 50.0

        latest_enroll = _grade_to_min_year(target_grades, today)
        if latest_enroll != 9999 and enrollment_year > latest_enroll:
            return 40.0  # 年级低于要求（入学更晚）
        return 60.0  # 年级超出范围

    def _score_interest(self, user: dict, item: dict) -> float:
        """维度三：兴趣匹配度（默认权重见 config.yaml / _DEFAULT_WEIGHTS）。

        用户 interests 与项目 tags/category 的重合度。
        """
        user_interests = user.get("interests", []) or []
        reqs = item.get("requirements", {})
        if not isinstance(reqs, dict):
            return self._default_if_missing("兴趣匹配", "", 70.0)

        tags = list(reqs.get("tags", []) or [])
        category = (reqs.get("category", "") or "").strip()
        # 跳过无区分度的 category，避免与 type 重复干扰兴趣匹配
        if category and category.lower() not in ("unknown", "学科竞赛", "其他"):
            tags.append(category)

        if not user_interests or not tags:
            return 70.0  # 任一方无标签时给默认分

        overlap = _conceptual_overlap(user_interests, tags)

        if overlap >= 2:
            return 100.0
        elif overlap == 1:
            return 70.0
        else:
            return 10.0  # 无概念重合

    def _score_ability(self, user: dict, item: dict, corpus: str = None) -> float:
        """维度四：能力匹配度（默认权重见 config.yaml / _DEFAULT_WEIGHTS）。

        用户 skills + competition_experience + research_experience + awards
        与项目 required_skills 比较。
        """
        user_skills = {str(s).lower() for s in (user.get("skills") or []) if s}
        if corpus is None:
            corpus = _user_ability_corpus(user)
        reqs = item.get("requirements", {})
        if not isinstance(reqs, dict):
            return self._default_if_missing("能力匹配", "", 70.0)

        required = reqs.get("required_skills", []) or []
        has_related_exp = self._has_related_experience(user, item, corpus)

        if not required:
            # 无明确技能要求时，有相关经历给更高分
            return 85.0 if has_related_exp else 70.0

        overlap, total = _count_skill_overlap(user_skills, required, corpus)
        ratio = overlap / total if total > 0 else 0

        if ratio >= 0.8 and has_related_exp:
            return 100.0
        if ratio >= 0.5 and has_related_exp:
            return 75.0
        if ratio >= 0.5:
            return 65.0
        if ratio > 0 and has_related_exp:
            return 60.0
        if ratio > 0:
            return 50.0
        if has_related_exp:
            return 45.0  # 技能标签未对齐，但有相关竞赛/科研经历
        return 25.0

    def _has_related_experience(self, user: dict, item: dict, corpus: str = None) -> bool:
        """检查用户是否有与项目相关的竞赛/科研经历。"""
        combined = corpus if corpus is not None else _user_ability_corpus(user)

        reqs = item.get("requirements", {})
        if not isinstance(reqs, dict):
            return False

        tags = reqs.get("tags", []) or []
        category = (reqs.get("category", "") or "").strip()
        keywords = list(tags)
        if category and category.lower() not in ("unknown", "学科竞赛", "其他"):
            keywords.append(category)

        for kw in keywords:
            text = str(kw).strip().lower()
            if len(text) >= 2 and text in combined:
                return True
        return False

    def _score_deadline(self, deadline_str: str, today: date,
                        available_time: str = "") -> float:
        """维度五：截止时间可行性。

        先按距离截止日分档，再结合 available_time 时间窗微调。
        """
        days = _days_until_deadline(deadline_str, today)
        if days == _DEADLINE_UNKNOWN:
            base = 70.0
        elif days > 30:
            base = 100.0
        elif days >= 15:
            base = 80.0
        elif days >= 7:
            base = 50.0
        elif days >= 0:
            base = 20.0
        else:
            return 0.0  # 已截止（外层已过滤，此处作兜底）

        # 若能解析用户可用时间窗，且截止日落在窗外，则降权
        month_range = _parse_available_month_range(available_time)
        if month_range and days not in (_DEADLINE_UNKNOWN, 99999) and days >= 0:
            from datetime import timedelta
            deadline_date = today + timedelta(days=days)
            (y1, m1), (y2, m2) = month_range
            start = date(y1, m1, 1)
            if m2 == 12:
                end = date(y2, 12, 31)
            else:
                end = date(y2, m2 + 1, 1) - timedelta(days=1)
            if not (start <= deadline_date <= end):
                base = min(base, 40.0)
        return base

    def _score_team(self, user: dict, item: dict) -> float:
        """维度六：团队匹配度（默认权重见 config.yaml / _DEFAULT_WEIGHTS）。

        用户 team_status 与项目 team_requirement 比较。
        「寻找队友」应对组队项目给高分，而非当作单人冲突。
        """
        user_team = (user.get("team_status") or "").strip()
        reqs = item.get("requirements", {})
        if not isinstance(reqs, dict):
            return self._default_if_missing("团队匹配", user_team, 70.0)

        team_req = (reqs.get("team_requirement", "") or "").strip()

        if not team_req:
            return 90.0  # 无要求

        user_solo = user_team == "单人申报"
        user_looking = user_team == "寻找队友"
        user_has_team = user_team == "已有团队"
        req_alone = team_req in ("单人", "个人", "单人申报")
        req_team = team_req in ("组队", "团队", "3-5人")
        req_any = team_req in ("均可", "不限", "单人/组队")

        if req_any:
            return 90.0
        if user_solo and req_alone:
            return 100.0
        if user_has_team and req_team:
            return 100.0
        if user_looking and req_team:
            return 90.0  # 正在找队友，适合组队赛
        if user_looking and req_alone:
            return 70.0  # 可转单人参赛
        if user_solo and req_team:
            return 30.0  # 明确单人申报但项目要求组队
        if user_has_team and req_alone:
            return 60.0

        return 60.0

    # ==================================================================
    # 推荐文案生成
    # ==================================================================

    def _to_level(self, score: float) -> tuple:
        """根据综合得分返回 (等级代码, 等级中文描述)。"""
        for threshold, code, label in self.level_thresholds:
            if score >= threshold:
                return code, label
        return "C", "不推荐"

    def _build_reason(self, detail: dict) -> str:
        """构建推荐理由：优先列出高分维度；若无高分则回退到相对优势维度。"""
        high_dims = [
            f"{_DIM_NAME_MAP[k]}({int(detail[k])}分)"
            for k in _COPY_DIM_KEYS
            if detail.get(k, 0) >= 85
        ]
        if high_dims:
            return "、".join(high_dims)

        # 避免 reason 为空：取得分最高的 1~2 个文案维度
        ranked = sorted(
            ((k, detail.get(k, 0)) for k in _COPY_DIM_KEYS if k in detail),
            key=lambda x: x[1],
            reverse=True,
        )
        top = [
            f"{_DIM_NAME_MAP[k]}({int(score)}分)"
            for k, score in ranked[:2]
            if score > 0
        ]
        return "、".join(top) if top else "综合匹配一般，可作为备选关注"

    def _build_risk(self, detail: dict) -> str:
        """根据得分细节构建风险提示文字。

        仅关注兴趣/能力/截止/团队；专业/年级不符合已由硬性门槛拦截或属默认高分。
        """
        low_dims = [
            f"{_DIM_NAME_MAP[k]}({int(detail[k])}分)"
            for k in _COPY_DIM_KEYS
            if detail.get(k, 0) < 50
        ]

        if not low_dims:
            # 团队要求略低（50-69）时补充提示，常见于「已有团队 vs 单人赛」
            team_score = detail.get("team_score", 100)
            if 50 <= team_score < 70:
                return f"提示: {_DIM_NAME_MAP['team_score']}({int(team_score)}分)，建议确认参赛形式"
            return "无明显风险，建议优先申请"
        return f"风险提示: {'; '.join(low_dims)}"

    def _build_action(self, level_code: str, detail: dict) -> str:
        """根据推荐等级和得分细节生成建议行动文字。"""
        if level_code == "S":
            return "强烈建议立即准备申请材料，优先排序靠前"
        elif level_code == "A":
            actionable = {k: detail[k] for k in _COPY_DIM_KEYS if k in detail}
            if actionable:
                low_key, low_score = min(actionable.items(), key=lambda x: x[1])
                if low_score < 70:
                    return f"建议关注{_DIM_NAME_MAP[low_key]}后尽快申请"
            return "建议尽快准备申请材料"
        elif level_code == "B":
            actionable = {k: detail[k] for k in _COPY_DIM_KEYS if k in detail}
            if actionable:
                low_key, low_score = min(actionable.items(), key=lambda x: x[1])
                if low_score < 50 and low_key in _DIM_NAME_MAP:
                    return f"建议关注{_DIM_NAME_MAP[low_key]}，同时寻找更匹配的备选项目"
            return "建议关注，同时寻找更匹配的备选项目"
        else:
            return "不建议投入精力，推荐关注其他项目"

    # ==================================================================
    # 响应构建工具函数
    # ==================================================================

    def _success_response(self, task_id: str, data: dict, message: str = "") -> dict:
        """构建统一成功响应。"""
        return {
            "task_id":    task_id,
            "agent_name": self.AGENT_NAME,
            "status":     "success",
            "data":       data,
            "message":    message or "Agent executed successfully.",
            "error":      None,
            "next_action": None,
            "metadata":   {},
        }

    def _error_response(self, task_id: str, error_type: str,
                         error_message: str, suggestion: str = "") -> dict:
        """构建统一失败响应（遵循 PROJECT_SPEC 错误格式）。"""
        return {
            "task_id":    task_id,
            "agent_name": self.AGENT_NAME,
            "status":     "failed",
            "data":       {},
            "message":    error_message,
            "error":      {
                "error_type":    error_type,
                "error_message": error_message,
                "suggestion":    suggestion,
            },
            "next_action": None,
            "metadata":   {},
        }

    def _need_input_response(self, task_id: str, message: str) -> dict:
        """构建"需要用户补充信息"响应。"""
        return {
            "task_id":    task_id,
            "agent_name": self.AGENT_NAME,
            "status":     "need_input",
            "data":       {},
            "message":    message,
            "error":      None,
            "next_action": "ask_user",
            "metadata":   {},
        }

    def _default_if_missing(self, dim_name: str, user_value: str,
                            fallback: float) -> float:
        """数据缺失时的默认分值，并在 recommend 阶段提示用户。"""
        _ = dim_name, user_value  # 后续可扩展为日志记录
        return fallback


# ---------------------------------------------------------------------------
# 自测入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """自测：读取 config.yaml + data/processed 标准样例，跑通推荐并写入 data/output/。"""
    import json

    config = _load_config()
    agent = RecommendationAgent(config)
    test_input = build_sample_input(config)

    result = agent.run(test_input)

    # 最终结果保存到 data/output/（路径来自 config.yaml）
    storage = config.get("storage", {}) if isinstance(config, dict) else {}
    output_dir = _resolve_path(storage.get("output_path", "./data/output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    task_id = result.get("task_id") or "sample"
    output_file = output_dir / f"recommendation_result_{task_id}.json"
    output_file.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[saved] {output_file}")
