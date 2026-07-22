"""SourceClient 抽象基类 — 定义统一的数据获取接口，内置连接重试。"""

import time
import random
import logging
from abc import ABC, abstractmethod
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class BaseSourceClient(ABC):
    """每个平台实现自己的 Client 子类，封装 HTTP 请求逻辑。

    内置功能:
      - 连接重试 (max_retries 次，指数退避)
      - 请求间隔抖动 (避免触发反爬)

    子类必须实现:
      - get_contests(page, limit) → dict|str
      - get_contest_detail(contest_id) → dict|str

    子类可覆盖初始化参数:
      - max_retries: 连接失败最大重试次数 (默认 3)
      - retry_backoff_base: 退避基数秒 (默认 2)
    """

    max_retries: int = 3
    retry_backoff_base: float = 2.0

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self._transport = self._build_transport()
        self._client: Optional[httpx.Client] = None

    def _build_transport(self) -> httpx.HTTPTransport:
        """创建带重试的传输层。"""
        return httpx.HTTPTransport(retries=self.max_retries)

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.timeout,
                headers=self._default_headers(),
                transport=self._transport,
                follow_redirects=True,
            )
        return self._client

    def _default_headers(self) -> dict:
        """子类可覆盖以自定义默认请求头。"""
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    def close(self):
        if self._client:
            self._client.close()
            self._client = None

    def get_with_retry(self, url: str, params: dict = None, max_attempts: int = 3) -> httpx.Response:
        """带重试的 GET 请求，指数退避 + 随机抖动。"""
        last_exc = None
        for attempt in range(max_attempts):
            try:
                resp = self.client.get(url, params=params)
                resp.raise_for_status()
                return resp
            except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as e:
                last_exc = e
                if attempt < max_attempts - 1:
                    wait = self.retry_backoff_base ** (attempt + 1) + random.uniform(0, 1)
                    logger.warning("%s 连接失败 (尝试 %d/%d), %.1fs 后重试: %s",
                                   url[:60], attempt + 1, max_attempts, wait, e)
                    time.sleep(wait)
                else:
                    logger.error("%s 连接最终失败 (%d 次尝试): %s", url[:60], max_attempts, e)
            except httpx.HTTPStatusError as e:
                # 4xx 不重试（如 404），5xx 可重试
                if 500 <= e.response.status_code < 600 and attempt < max_attempts - 1:
                    wait = self.retry_backoff_base ** (attempt + 1) + random.uniform(0, 1)
                    logger.warning("%s 服务端错误 %d (尝试 %d/%d), %.1fs 后重试",
                                   url[:60], e.response.status_code, attempt + 1, max_attempts, wait)
                    time.sleep(wait)
                    continue
                raise
        raise last_exc

    # ---- 抽象接口 ----

    @abstractmethod
    def get_contests(self, page: int = 1, limit: int = 20):
        """获取竞赛列表。"""
        ...

    @abstractmethod
    def get_contest_detail(self, contest_id: str):
        """获取单条竞赛详情。"""
        ...

    def get_featured(self):
        """获取首页/推荐竞赛，默认返回空。"""
        return []

    def get_config(self):
        """获取站点配置，默认返回空。"""
        return {}
