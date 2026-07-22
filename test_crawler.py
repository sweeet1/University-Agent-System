"""测试爬虫功能 — 独立运行，测试各数据源的 Client + Parser 联调。

用法:
    python test_crawler.py                     # 测试所有 5 个网站
    python test_crawler.py saikr               # 只测试赛氪
    python test_crawler.py saikr 52jingsai     # 测试指定网站
    python test_crawler.py --dry-run           # 干跑（只验证注册和配置，不发请求）
"""

import json
import sys
import os
import logging
from datetime import datetime

# 每次 print 后立即刷新，避免在卡顿时看不到输出
_print = print
def print(*args, **kwargs):
    kwargs.setdefault("flush", True)
    _print(*args, **kwargs)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("crawler_test")

# 确保项目根目录在 sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from agents.info_collect.registry import SourceRegistry
from agents.info_collect.storage import Storage
from agents.info_collect.crawler import Crawler

ALL_SOURCES = ["saikr", "52jingsai", "ali_tianchi", "heywhale", "datafountain"]


def banner(text: str):
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}")


def test_registry():
    """验证所有数据源已注册。"""
    banner("1. 注册表检查")
    registered = SourceRegistry.list_all()
    print(f"已注册数据源: {registered}")
    print(f"总计: {len(registered)} 个")

    for name in registered:
        spec = SourceRegistry.get(name)
        client = spec.client_class()
        parser = spec.parser_class({})
        print(f"  {name:20s}  Client={spec.client_class.__name__:25s}  Parser={spec.parser_class.__name__:25s}")
        client.close()

    missing = set(ALL_SOURCES) - set(registered)
    if missing:
        logger.warning("未注册的数据源: %s", missing)
    else:
        print("  >>> 全部 5 个数据源已就绪")


def test_parser_unit():
    """对各 parser 做单元检查（不发网络请求）。"""
    banner("2. Parser 单元检查")

    # 模拟 JSON API 数据
    mock_json = {"data": {"list": [{"title": "测试竞赛", "url": "/test/1"}]}}

    for name in ALL_SOURCES:
        spec = SourceRegistry.get(name)
        if spec is None:
            print(f"  {name}: 未注册，跳过")
            continue
        parser = spec.parser_class({})
        try:
            result = parser.parse_list(mock_json)
            empty = parser.parse_list({})
            detail = parser.parse_detail({})
            print(f"  {name:20s}  parse_list(mock)={len(result)}  parse_list(empty)={len(empty)}  parse_detail(empty)={'OK' if isinstance(detail, dict) else 'FAIL'}")
        except Exception as e:
            print(f"  {name:20s}  ERROR: {e}")


def test_crawler_dry_run(sources: list[str]):
    """验证 Crawler 能正确识别并准备采集指定数据源（不发实际请求）。"""
    banner("3. Crawler 干跑（验证调度逻辑）")

    config = {
        "info_collect": {
            "request_delay_min": 0.1,
            "request_delay_max": 0.3,
            "max_pages": 1,
        },
        "storage": {"raw_data_path": "./data/raw"},
    }
    storage = Storage("./data/raw")
    crawler = Crawler(config, storage)

    print(f"待采集数据源: {sources}")
    print(f"Crawler 配置: max_pages={crawler.max_pages}, delay={crawler.delay_min}-{crawler.delay_max}s")

    for s in sources:
        spec = SourceRegistry.get(s)
        if spec:
            print(f"  {s:20s} -> Client={spec.client_class.__name__}, Parser={spec.parser_class.__name__}")
        else:
            print(f"  {s:20s} -> 未注册!")

    # 检查 _match
    assert crawler._match({"title": "人工智能创新大赛"}, ["人工智能"])
    assert crawler._match({"contest_name": "全国数学建模"}, ["数学建模", "ACM"])
    assert not crawler._match({"title": "生物学竞赛"}, ["数学", "物理"])
    print("  >>> _match 关键字匹配逻辑正常")

    # 检查 _extract_ident
    from agents.info_collect.crawler import _extract_ident
    cases = [
        ("https://www.saikr.com/vse/58394", "58394"),
        ("https://www.52jingsai.com/article-23897-1.html", "article-23897-1"),
        ("https://www.datafountain.cn/competitions/1169", "1169"),
        ("https://tianchi.aliyun.com/competition/532495", "532495"),
    ]
    for url, expected in cases:
        result = _extract_ident(url)
        status = "OK" if result == expected else f"FAIL (got {result})"
        print(f"    _extract_ident({url}) = {result}  {status}")

    print(f"  >>> 干跑通过（{len(sources)} 个数据源）")


def test_crawl_live(source: str, keywords: list[str] | None = None, timeout: int = 10):
    """真实爬取单个数据源。timeout 默认 10 秒。"""
    banner(f"4. 真实爬取: {source}")

    # 各站点默认关键词（匹配常见的竞赛标题）
    DEFAULT_KEYWORDS = {
        "saikr": ["数学建模", "人工智能", "程序设计"],
        "52jingsai": ["人工智能", "大数据", "算法"],
        "ali_tianchi": ["算法", "AI", "大数据"],
        "heywhale": ["数据", "竞赛", "AI"],
        "datafountain": ["算法", "人工智能", "大数据"],
    }
    if keywords is None:
        keywords = DEFAULT_KEYWORDS.get(source, ["竞赛", "大赛"])

    config = {
        "info_collect": {
            "request_delay_min": 1,
            "request_delay_max": 3,
            "max_pages": 10,
            "client_timeout": timeout,
        },
        "storage": {"raw_data_path": "./data/raw"},
    }

    storage = Storage("./data/raw")
    crawler = Crawler(config, storage)
    log_id = storage.start_crawl_log(f"test_{source}", source)
    stats = {}  # 提前初始化

    print(f"关键词: {keywords}")
    print(f"最大页数: {crawler.max_pages}")
    print(f"开始爬取 {source} ...")

    try:
        items, stats = crawler.crawl(keywords, [source], max_results=5, log_id=log_id)
        pages = stats.get("pages_crawled", 0)
        total = stats.get("items_found", 0)
        new = stats.get("items_new", 0)
        updated = stats.get("items_updated", 0)

        print(f"\n结果: 爬取 {pages} 页, 匹配 {total} 条, 新增 {new} 条, 更新 {updated} 条")

        if items:
            print(f"\n前 {min(3, len(items))} 条结果:")
            for i, item in enumerate(items[:3], 1):
                print(f"  {i}. [{item.get('source', '?')}] {item.get('title', '无标题')[:60]}")
                print(f"     URL: {item.get('url', 'N/A')}")
                desc = item.get("description", "")
                if desc:
                    print(f"     描述: {desc[:100]}...")
        elif pages == 0:
            print("  提示: 爬虫未获取到任何页面数据，可能是网络不通或页面结构变化")
            print(f"  建议: 检查 {source} 网站是否能正常访问，或运行 --dry-run 验证注册表")
        else:
            # 有页面数据但关键词没匹配上 → 展示可用标题帮用户选词
            total = stats.get("total_parsed", 0)
            print(f"  >>> 关键词 {keywords} 在 {pages} 页 / {total} 条中未匹配 <<<")
            if pages < 10:
                print(f"  注意: 该数据源仅返回 {pages} 页数据（不支持无限翻页），非配置问题")
            available = stats.get("available_titles", [])
            if available:
                if len(available) > 10:
                    print(f"  当前页面可用的标题 (共 {len(available)} 条，展示前 10 条):")
                else:
                    print(f"  当前页面可用的标题 ({len(available)} 条):")
                for t in available[:10]:
                    print(f"    - {t[:60]}")
            print(f"  建议: 使用 --keywords 更换关键词，或用 --keywords '*' 查看全部")

        return items, stats

    except Exception as e:
        logger.exception("爬取 %s 失败", source)
        print(f"  错误: {e}")
        return [], {}
    finally:
        storage.update_crawl_log(
            log_id,
            pages_crawled=stats.get("pages_crawled", 0),
            items_found=stats.get("items_found", 0),
            items_new=stats.get("items_new", 0),
            items_updated=stats.get("items_updated", 0),
            status="completed",
            finished_at=datetime.now().isoformat(),
        )


def main():
    # 解析 CLI 参数
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    timeout = 10  # 默认 10 秒超时
    keywords = None  # None 表示使用各站点的默认关键词

    for i, a in enumerate(args):
        if a == "--timeout" and i + 1 < len(args):
            timeout = int(args[i + 1])
        if a == "--keywords" and i + 1 < len(args):
            raw = args[i + 1]
            keywords = ["*"] if raw == "*" else raw.split(",")

    sources = [a for a in args if not a.startswith("--") and (a in ALL_SOURCES or a.endswith("jingsai"))]
    # 过滤掉 --timeout, --keywords 后面的值
    flag_values = []
    for i, a in enumerate(args):
        if a in ("--timeout", "--keywords") and i + 1 < len(args):
            flag_values.append(args[i + 1])
    sources = [a for a in sources if a not in flag_values]

    if not sources:
        sources = ALL_SOURCES.copy()

    # 验证 sources
    registered = SourceRegistry.list_all()
    invalid = [s for s in sources if s not in registered]
    if invalid:
        print(f"无效的数据源: {invalid}")
        print(f"可用: {registered}")
        sys.exit(1)

    print(f"数据源: {sources}")
    print(f"模式: {'干跑' if dry_run else '真实爬取'}")
    print(f"超时: {timeout}s")
    if keywords:
        print(f"关键词: {keywords}")

    test_registry()
    test_parser_unit()
    test_crawler_dry_run(sources)

    if not dry_run:
        for source in sources:
            test_crawl_live(source, keywords=keywords, timeout=timeout)

    banner("测试完成")
    print(f"测试的数据源: {', '.join(sources)}")
    print("用法:")
    print("  python test_crawler.py --dry-run                        # 干跑")
    print("  python test_crawler.py saikr                           # 测试赛氪")
    print("  python test_crawler.py 52jingsai --keywords 竞赛,英语  # 中文关键词")
    print("  python test_crawler.py 52jingsai --keywords '*'        # 匹配全部")



if __name__ == "__main__":
    main()
