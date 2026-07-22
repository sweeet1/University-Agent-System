"""52jingsai 竞赛数据解析器 — 从 /bisai/ 列表页和详情页提取结构化字段。

列表页结构 (div.bbda.list_bbda):
  每项格式: 标题链接|摘要||截止/报名信息||主办方信息|分类:|分类名|发布日期|浏览量

示例:
  2026年全国大学生英语翻译能力竞赛|翻译能力竞赛官网：www.ncetac.com
  || 报名时间：即日起至8月6日，赛题发布时间：7月8日上午10点
  || 主办单位：中国外文局亚太传播中心
  |分类:|英语竞赛|2026-7-22 09:24|46798
"""

import json
import re
from datetime import datetime
from bs4 import BeautifulSoup
from .base import BaseParser

DETAIL_BASE = "https://www.52jingsai.com"


class Jingsai52Parser(BaseParser):
    """解析 52jingsai /bisai/ 页面。"""

    def __init__(self, config: dict):
        super().__init__(config)

    # ---- 列表解析 ----

    def parse_list(self, data) -> list[dict]:
        if isinstance(data, str):
            return self._parse_html_list(data)
        if isinstance(data, dict):
            return self._parse_json_list(data)
        return []

    def _parse_html_list(self, html: str) -> list[dict]:
        """从 /bisai/ 页面的 dl.bbda.list_bbda 提取竞赛条目。

        每个 dl 结构:
          <dt class="xs2_tit"><a class="xi2" href="article-XXXXX.html">竞赛标题</a></dt>
          <dd class="xs2 cl">摘要 || 报名时间 || 主办方 <div class="list_info">分类: XX YYYY-M-D HH:MM</div></dd>
        """
        soup = BeautifulSoup(html, "lxml")
        results = []
        seen = set()

        for dl in soup.select("dl.bbda.list_bbda"):
            # 标题 — 在 dt.xs2_tit > a.xi2 里
            title_a = dl.select_one("dt.xs2_tit a.xi2")
            if not title_a:
                continue

            href = title_a.get("href", "")
            title = title_a.get_text(strip=True)
            if not title or not href:
                continue

            url = self._normalize_url(href)
            if url in seen:
                continue
            seen.add(url)

            # 摘要/时间/主办方 — 在 dd.xs2.cl 里
            dd = dl.select_one("dd.xs2.cl")
            dd_text = dd.get_text(separator="||", strip=True) if dd else ""

            # 分类 (从 list_info 中提取)
            category = ""
            list_info = dl.select_one(".list_info")
            if list_info:
                # 取 "分类:" 后面的 a 标签或纯文本
                cat_a = list_info.find("a")
                if cat_a:
                    category = cat_a.get_text(strip=True)
                else:
                    m = re.search(r"分类[：:]\s*(.+?)(?:\d{4}-\d{1,2}-\d{1,2})", list_info.get_text())
                    if m:
                        category = m.group(1).strip()

            # 发布时间
            publish_date = ""
            if list_info:
                m = re.search(r"(\d{4}-\d{1,2}-\d{1,2})", list_info.get_text())
                if m:
                    publish_date = m.group(1)

            # 主办方 — 从 dd_text 中提取
            organizer = ""
            organizer_list = []
            org_m = re.search(
                r"\|\|\s*(?:主办单位|主办方|征集单位|组织单位)[：:]\s*(.+?)(?:\|\||$)",
                dd_text
            )
            if org_m:
                org_raw = org_m.group(1).strip()
                organizer = org_raw
                organizer_list = [
                    n.strip() for n in re.split(r"[、，,;；]", org_raw)
                    if n.strip() and len(n.strip()) > 1
                ]

            # 截止日期
            regist_end = ""
            for pat in [
                r"截止时间[：:]\s*(.+?)(?:[，\|\|]|$)",
                r"截止日期[：:]\s*(.+?)(?:[，\|\|]|$)",
                r"报名截止[：:]\s*(.+?)(?:[，\|\|]|$)",
                r"报名时间[：:]\s*即日起[至到—\-]\s*(.+?)(?:[，\|\|]|$)",
                r"征集截止时间[：:]\s*(.+?)(?:[，\|\|]|$)",
                r"考试时间[：:]\s*(.+?)(?:[，\|\|]|$)",
            ]:
                m = re.search(pat, dd_text)
                if m:
                    regist_end = self._norm_date(m.group(1).strip())
                    if regist_end:
                        break

            results.append({
                "title": title,
                "url": url,
                "source": "52jingsai",
                "raw_text": json.dumps({"dd_text": dd_text}, ensure_ascii=False),
                "publish_date": publish_date,
                "collected_at": datetime.now().isoformat(),
                "description": dd_text[:200] if dd_text else "",
                "organizer": organizer,
                "organizer_list": organizer_list,
                "co_organizers": [],
                "supporters": [],
                "regist_start": "",
                "regist_end": regist_end,
                "contest_start": "",
                "contest_end": "",
                "category": category,
                "level": "",
                "attachments": [],
            })

        return results

    # ---- merge_detail (对齐 saikr 格式) ----
    # 策略：/bisai/ 列表页已有干净的 organizer、category、regist_end，
    #       详情页只补充 description、contest_start、contest_end。
    #       详情页的脏字段不覆盖列表页已有的干净值。

    def merge_detail(self, item: dict, detail_fields: dict) -> dict:
        page_title = detail_fields.pop("page_title", "")
        if page_title and len(page_title) > len(item["title"]):
            item["title"] = page_title

        # 只取 detail 中有用且不会污染列表数据的字段
        for key in ("description", "contest_start", "contest_end", "co_organizers", "supporters"):
            detail_val = detail_fields.get(key)
            if detail_val and not item.get(key):
                item[key] = detail_val

        # 列表页没有 organizer 时才从 detail 补充
        if not item.get("organizer") and detail_fields.get("organizer"):
            item["organizer"] = detail_fields["organizer"]
        if not item.get("organizer_list") and detail_fields.get("organizer_list"):
            item["organizer_list"] = detail_fields["organizer_list"]
        if not item.get("regist_end") and detail_fields.get("regist_end"):
            item["regist_end"] = detail_fields["regist_end"]

        item.pop("page_title", None)

        list_data = {}
        try:
            list_data = json.loads(item.get("raw_text", "{}"))
        except (json.JSONDecodeError, TypeError):
            pass
        item["raw_text"] = json.dumps(
            {"list": list_data, "detail": json.dumps(detail_fields, ensure_ascii=False)},
            ensure_ascii=False,
        )
        return item

    # ---- 详情解析 ----

    def parse_detail(self, data) -> dict:
        if isinstance(data, str):
            if data.strip().startswith("{"):
                try:
                    return self._parse_json_detail(json.loads(data))
                except (json.JSONDecodeError, TypeError):
                    pass
            return self._parse_html_detail(data)
        if isinstance(data, dict):
            return self._parse_json_detail(data)
        return self._empty_detail()

    def _parse_html_detail(self, html: str) -> dict:
        soup = BeautifulSoup(html, "lxml")

        # 标题
        h1 = soup.find("h1")
        page_title = h1.get_text(strip=True) if h1 else ""

        # 正文
        article_td = soup.select_one("#article_content")
        description = ""
        if article_td:
            for s in article_td.find_all(["script", "style"]):
                s.decompose()
            raw = article_td.get_text(separator="\n", strip=True)
            description = self._clean_description(raw)

        # 汇总文本
        vw_div = soup.select_one(".vw") or soup.select_one("#ct")
        vw_text = vw_div.get_text(strip=True) if vw_div else ""
        search_text = vw_text + "\n" + description

        return {
            "description": description,
            "organizer": self._ext_org_text(search_text),
            "organizer_list": self._ext_org_list(search_text),
            "co_organizers": self._ext_co_org_list(description),
            "supporters": [],
            "regist_start": "",
            "regist_end": self._ext_regist_end(search_text),
            "contest_start": self._ext_contest_start(search_text),
            "contest_end": self._ext_contest_end(search_text),
            "category": "",
            "level": "",
            "attachments": [],
            "page_title": page_title,
            "publish_date": "",
        }

    # ---- 字段提取 ----

    def _ext_org_text(self, text: str) -> str:
        m = re.search(r"(?:主办单位|主办方)[：:]\s*(.+?)$", text, re.MULTILINE)
        if m:
            raw = m.group(1).strip()
            line = raw.split("\n")[0].strip()
            # 机构名通常不超过 80 字，超过说明匹配到了整段正文，放弃
            if len(line) > 80:
                return ""
            return line
        return ""

    def _ext_org_list(self, text: str) -> list[str]:
        org_text = self._ext_org_text(text)
        if not org_text or len(org_text) > 80:
            return []
        return [n.strip() for n in re.split(r"[、，,;；]", org_text)
                if n.strip() and len(n.strip()) > 1]

    def _ext_co_org_list(self, text: str) -> list[str]:
        m = re.search(r"(?:二[、.]\s*)?(?:协办单位|承办单位)\s*\n", text)
        if not m:
            return []
        section = text[m.end():m.end() + 1000]
        items = []
        org_kw = re.compile(r"大学|学院|协会|研究院|组委会|杂志|中心|学会|委员会|外国语|社团|教研室|企业|公司")
        for line in section.split("\n"):
            line = line.strip()
            if not line:
                break
            if re.match(r"[三三四五六七八九十]+[、.）)]", line):
                break
            if org_kw.search(line) and len(line) >= 3:
                sub = [s.strip() for s in re.split(r"[、，]", line)]
                for si in sub:
                    si = re.sub(r"等[。.]?$", "", si).strip()
                    if org_kw.search(si) and si not in items:
                        items.append(si)
        return items

    def _ext_regist_end(self, text: str) -> str:
        for pat in [
            r"报名截止时间[：:]\s*(.+?)(?:\n|$)",
            r"初赛截止日期[：:]\s*(.+?)(?:\n|$)",
        ]:
            m = re.search(pat, text)
            if m:
                return self._norm_date(m.group(1).strip())
        return ""

    def _ext_contest_start(self, text: str) -> str:
        m = re.search(r"(?:初赛时间|考试时间)[：:]\s*(.+?)(?:\n|$)", text)
        if m:
            raw = m.group(1).strip()
            raw = re.sub(r"（[^）]*）", "", raw)
            raw = re.split(r"\|\|", raw)[0]
            return raw.replace("\n", "")
        return ""

    def _ext_contest_end(self, text: str) -> str:
        m = re.search(r"(?:决赛时间|决赛获奖公示时间)[：:]\s*(.+?)(?:\n|$)", text)
        if m:
            return re.sub(r"（[^）]*）", "", m.group(1).strip())
        return ""

    # ---- 工具 ----

    @staticmethod
    def _clean_description(text: str) -> str:
        for marker in ["暂时没有组队需求", "官网报名地址："]:
            idx = text.find(marker)
            if idx > len(text) * 0.5:
                text = text[:idx].strip()
                break
        idx = text.find("我爱竞赛网赛事交流总群")
        if idx > len(text) * 0.5:
            text = text[:idx].strip()
        return text

    @staticmethod
    def _norm_date(s: str) -> str:
        if not s:
            return ""
        s = s.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return s
        m = re.match(r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})[日号]?", s)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = re.match(r"(\d{1,2})月(\d{1,2})[日号]?", s)
        if m:
            return f"{datetime.now().year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        m = re.search(r"(\d{1,2})月(\d{1,2})[日号]?", s)
        if m:
            return f"{datetime.now().year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        return s

    @staticmethod
    def _normalize_url(href: str) -> str:
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            return f"{DETAIL_BASE}{href}"
        return f"{DETAIL_BASE}/{href}"

    @staticmethod
    def _empty_detail() -> dict:
        return {
            "description": "", "organizer": "", "organizer_list": [],
            "co_organizers": [], "supporters": [],
            "regist_start": "", "regist_end": "",
            "contest_start": "", "contest_end": "",
            "category": "", "level": "", "attachments": [],
            "page_title": "", "publish_date": "",
        }

    # ---- JSON 备用 ----

    def _parse_json_list(self, data: dict) -> list[dict]:
        items = data.get("data", {}).get("list") or data.get("list") or data.get("items") or []
        results = []
        for item in items:
            results.append({
                "title": item.get("title", ""),
                "url": self._normalize_url(item.get("url", "")),
                "source": "52jingsai",
                "raw_text": json.dumps(item, ensure_ascii=False),
                "publish_date": item.get("publish_date", ""),
                "collected_at": datetime.now().isoformat(),
                "description": "",
                "organizer": item.get("organizer", ""),
                "organizer_list": item.get("organizer_list", []),
                "co_organizers": [],
                "supporters": [],
                "regist_start": "",
                "regist_end": item.get("regist_end", ""),
                "contest_start": "",
                "contest_end": "",
                "category": item.get("category", ""),
                "level": "",
                "attachments": [],
            })
        return results

    def _parse_json_detail(self, detail: dict) -> dict:
        content = detail.get("content") or detail.get("description") or ""
        desc = _html_to_text(content) if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        return {
            "description": desc,
            "organizer": detail.get("organizer") or "",
            "organizer_list": [],
            "co_organizers": [], "supporters": [],
            "regist_start": "", "regist_end": "",
            "contest_start": "", "contest_end": "",
            "category": "", "level": "", "attachments": [],
            "page_title": "", "publish_date": "",
        }


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(separator="\n", strip=True)


# ---- 自注册 ----
from ..registry import SourceRegistry  # noqa: E402
from ..clients.jingsai52 import Jingsai52Client  # noqa: E402

SourceRegistry.register("52jingsai", Jingsai52Client, Jingsai52Parser)
