"""API client for Boss Zhipin with rate limiting, retry, and anti-detection."""

from __future__ import annotations

import logging
import random
import time
import urllib.parse
from collections import deque
from typing import Any

import httpx

from .constants import (
    BASE_URL,
    CITY_CODES,
    DELIVER_LIST_URL,
    FRIEND_ADD_URL,
    FRIEND_LIST_URL,
    GEEK_GET_JOB_URL,
    GEEK_FRIEND_LIST_URL,
    GEEK_HISTORY_MSG_URL,
    GEEK_LAST_MSG_URL,
    HEADERS,
    INTERVIEW_DATA_URL,
    JOB_CARD_URL,
    JOB_DETAIL_URL,
    JOB_HISTORY_URL,
    JOB_SEARCH_URL,
    RESUME_BASEINFO_URL,
    RESUME_EXPECT_URL,
    RESUME_STATUS_URL,
    USER_INFO_URL,
    WEB_GEEK_CHAT_URL,
    WEB_GEEK_HISTORY_URL,
    WEB_GEEK_JOB_URL,
    WEB_GEEK_RECOMMEND_URL,
)
from .exceptions import BossApiError, ParamError, RateLimitError, SessionExpiredError

logger = logging.getLogger(__name__)


class BossClient:
    """Boss Zhipin API client with Gaussian jitter, exponential backoff, and session-stable identity.

    Anti-detection strategy:
    - Gaussian jitter delay between requests (~1s mean, σ=0.3)
    - 5% chance of a random long pause (2-5s) to mimic reading behavior
    - Exponential backoff on HTTP 429/5xx (up to 3 retries)
    - Response cookies merged back into session jar
    - Request counter for monitoring
    """

    def __init__(
        self,
        credential: object | None = None,
        timeout: float = 30.0,
        request_delay: float = 1.0,
        max_retries: int = 3,
    ):
        self.credential = credential
        self._timeout = timeout
        self._request_delay = request_delay
        self._base_request_delay = request_delay
        self._max_retries = max_retries
        self._last_request_time = 0.0
        self._request_count = 0
        self._rate_limit_count = 0
        self._recent_request_times: deque[float] = deque(maxlen=12)
        self._http: httpx.Client | None = None

    def _build_client(self) -> httpx.Client:
        cookies = {}
        if self.credential:
            cookies = self.credential.cookies
        return httpx.Client(
            base_url=BASE_URL,
            headers=dict(HEADERS),
            cookies=cookies,
            follow_redirects=True,
            timeout=httpx.Timeout(self._timeout),
        )

    @property
    def client(self) -> httpx.Client:
        if not self._http:
            raise RuntimeError("Client not initialized. Use 'with BossClient() as client:'")
        return self._http

    def __enter__(self) -> BossClient:
        self._http = self._build_client()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._http:
            self._http.close()
            self._http = None

    # ── Rate limiting ───────────────────────────────────────────────

    def _rate_limit_delay(self) -> None:
        """Enforce minimum delay with Gaussian jitter to mimic human browsing."""
        if self._request_delay <= 0:
            return
        elapsed = time.time() - self._last_request_time
        if elapsed < self._request_delay:
            # Gaussian jitter: mean=0.3, σ=0.15, clamped to [0, ∞)
            jitter = max(0, random.gauss(0.3, 0.15))
            # 5% chance of a long pause to mimic reading
            if random.random() < 0.05:
                jitter += random.uniform(2.0, 5.0)
            sleep_time = self._request_delay - elapsed + jitter
            logger.debug("Rate-limit delay: %.2fs", sleep_time)
            time.sleep(sleep_time)

        burst_penalty = self._burst_penalty_delay()
        if burst_penalty > 0:
            logger.debug("Burst penalty delay: %.2fs", burst_penalty)
            time.sleep(burst_penalty)

    def _burst_penalty_delay(self) -> float:
        """Add extra delay when a burst pattern looks less like human browsing."""
        if not self._recent_request_times:
            return 0.0

        now = time.time()
        recent_15s = sum(1 for ts in self._recent_request_times if now - ts <= 15)
        recent_45s = sum(1 for ts in self._recent_request_times if now - ts <= 45)

        if recent_45s >= 6:
            return random.uniform(4.0, 7.0)
        if recent_15s >= 3:
            return random.uniform(1.2, 2.8)
        return 0.0

    def _mark_request(self) -> None:
        now = time.time()
        self._last_request_time = now
        self._request_count += 1
        self._recent_request_times.append(now)

    @property
    def request_stats(self) -> dict[str, int | float]:
        """Return current request statistics."""
        return {
            "request_count": self._request_count,
            "last_request_time": self._last_request_time,
        }

    # ── Response handling ───────────────────────────────────────────

    def _merge_response_cookies(self, resp: httpx.Response) -> None:
        """Persist response Set-Cookie headers back into the session jar."""
        for name, value in resp.cookies.items():
            if value:
                self.client.cookies.set(name, value)

    def _headers_for_request(self, url: str, params: dict[str, Any] | None = None) -> dict[str, str]:
        """Build browser-like headers, including endpoint-specific Referer and zp_token."""
        headers = dict(HEADERS)
        # Add security headers that the boss web app sends with every request
        headers["X-Requested-With"] = "XMLHttpRequest"
        bst = self.client.cookies.get("bst", "")
        if bst:
            headers["zp_token"] = bst
        if url == JOB_SEARCH_URL:
            query = ""
            if params and params.get("query"):
                query = f"?{urllib.parse.urlencode({'query': params['query']})}"
            headers["Referer"] = f"{WEB_GEEK_JOB_URL}{query}"
        elif url == GEEK_GET_JOB_URL and params and params.get("tag") == 5:
            headers["Referer"] = WEB_GEEK_RECOMMEND_URL
        elif url == GEEK_GET_JOB_URL:
            headers["Referer"] = WEB_GEEK_CHAT_URL
        elif url in (JOB_CARD_URL, JOB_DETAIL_URL):
            headers["Referer"] = WEB_GEEK_JOB_URL
        elif url == JOB_HISTORY_URL:
            headers["Referer"] = WEB_GEEK_HISTORY_URL
        elif url in (FRIEND_LIST_URL, FRIEND_ADD_URL, GEEK_FRIEND_LIST_URL,
                      GEEK_LAST_MSG_URL, GEEK_HISTORY_MSG_URL):
            headers["Referer"] = WEB_GEEK_CHAT_URL
        return headers

    def _handle_response(self, data: dict[str, Any], action: str) -> dict[str, Any]:
        """Validate API response and return zpData, raise typed exceptions."""
        code = data.get("code", -1)

        if code == 0:
            return data.get("zpData", {})

        message = data.get("message", "Unknown error")

        if code == 37:
            raise SessionExpiredError()
        if code in (17, 19):
            raise ParamError(message, code=code)
        if code in (121, 122):
            raise BossApiError(
                f"{action}: 请求被安全系统拦截 (code={code})。"
                "此操作需要浏览器环境的安全验证，CLI 暂不支持。"
                "请在 BOSS直聘 网页端完成此操作。",
                code=code, response=data,
            )
        if code == 9:
            # Rate limited — auto-cooldown with exponential backoff
            self._rate_limit_count += 1
            cooldown = min(60, 10 * (2 ** (self._rate_limit_count - 1)))
            self._request_delay = max(self._request_delay, self._base_request_delay * 2)
            logger.warning(
                "Rate limited (count=%d), cooling down %.0fs, delay raised to %.1fs",
                self._rate_limit_count, cooldown, self._request_delay,
            )
            time.sleep(cooldown)
            raise RateLimitError()

        raise BossApiError(f"{action}: {message} (code={code})", code=code, response=data)

    # ── Request with retry ──────────────────────────────────────────

    def _request(self, method: str, url: str, **kwargs) -> dict[str, Any]:
        """Execute HTTP request with rate-limit delay, retry, and cookie merge."""
        self._rate_limit_delay()
        last_exc: Exception | None = None
        params = kwargs.get("params")
        merged_headers = self._headers_for_request(url, params=params)
        request_headers = kwargs.pop("headers", None)
        if request_headers:
            merged_headers.update(request_headers)

        for attempt in range(self._max_retries):
            t0 = time.time()
            try:
                resp = self.client.request(method, url, headers=merged_headers, **kwargs)
                elapsed = time.time() - t0
                self._merge_response_cookies(resp)
                self._mark_request()

                logger.info(
                    "[#%d] %s %s → %d (%.2fs)",
                    self._request_count, method, url[:60], resp.status_code, elapsed,
                )

                # Retry on server errors
                if resp.status_code in (429, 500, 502, 503, 504):
                    wait = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        "HTTP %d from %s, retrying in %.1fs (attempt %d/%d)",
                        resp.status_code, url[:80], wait, attempt + 1, self._max_retries,
                    )
                    time.sleep(wait)
                    continue

                # For non-server errors (4xx except 404), raise immediately
                if resp.status_code == 404:
                    # Some endpoints return 404 when anti-bot blocks the request
                    text = resp.text
                    if text.strip().startswith("{"):
                        return resp.json()
                    raise BossApiError(f"接口不存在: {url} (HTTP 404)", code=404)

                resp.raise_for_status()

                # Check for HTML responses (redirect to login page)
                text = resp.text
                if text.startswith("<"):
                    raise BossApiError(f"Received HTML instead of JSON from {url} (possible auth redirect)")

                return resp.json()

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                elapsed = time.time() - t0
                last_exc = exc
                wait = (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    "[#%d] %s %s → Network error: %s (%.2fs), retrying in %.1fs (attempt %d/%d)",
                    self._request_count + 1, method, url[:60], exc, elapsed, wait,
                    attempt + 1, self._max_retries,
                )
                time.sleep(wait)

        if last_exc:
            raise BossApiError(f"Request failed after {self._max_retries} retries: {last_exc}") from last_exc
        raise BossApiError(f"Request failed after {self._max_retries} retries")

    def _get(self, url: str, params: dict[str, Any] | None = None, action: str = "") -> dict[str, Any]:
        """GET request with response validation and rate-limit retry."""
        data = self._request("GET", url, params=params)
        try:
            result = self._handle_response(data, action)
            # Reset rate-limit counter on success
            self._rate_limit_count = 0
            return result
        except RateLimitError:
            # Auto-retry once after cooldown (cooldown already happened in _handle_response)
            logger.info("Retrying after rate-limit cooldown...")
            data = self._request("GET", url, params=params)
            result = self._handle_response(data, action)
            self._rate_limit_count = 0
            return result

    # ── Job Search & Browse ─────────────────────────────────────────

    def search_jobs(
        self,
        query: str,
        city: str = "101010100",
        page: int = 1,
        page_size: int = 15,
        experience: str | None = None,
        degree: str | None = None,
        salary: str | None = None,
        industry: str | None = None,
        scale: str | None = None,
        stage: str | None = None,
        job_type: str | None = None,
    ) -> dict[str, Any]:
        """Search jobs."""
        params: dict[str, Any] = {
            "query": query,
            "city": city,
            "page": page,
            "pageSize": page_size,
        }
        if experience:
            params["experience"] = experience
        if degree:
            params["degree"] = degree
        if salary:
            params["salary"] = salary
        if industry:
            params["industry"] = industry
        if scale:
            params["scale"] = scale
        if stage:
            params["stage"] = stage
        if job_type:
            params["jobType"] = job_type
        return self._get(JOB_SEARCH_URL, params=params, action="搜索职位")

    def get_recommend_jobs(self, page: int = 1) -> dict[str, Any]:
        """Get personalized job recommendations.

        The live web page currently loads recommendation cards from
        ``/wapi/zprelation/interaction/geekGetJob`` with tag=5 rather
        than the older ``/wapi/zpgeek/pc/recommend/job/list.json`` path.
        Normalize that payload back into the CLI's historical shape.
        """
        data = self._get(
            GEEK_GET_JOB_URL,
            params={"page": page, "tag": 5, "isActive": "true"},
            action="推荐职位",
        )
        if "jobList" in data:
            return data

        card_list = data.get("cardList", [])
        return {
            "jobList": card_list,
            "hasMore": data.get("hasMore", False),
            "totalCount": data.get("totalCount", len(card_list)),
            "page": data.get("page", page),
            "startIndex": data.get("startIndex", 0),
            "type": data.get("type", 2),
            "lid": data.get("lid", ""),
        }

    def get_job_card(self, security_id: str, lid: str) -> dict[str, Any]:
        """Get job card info (hover preview)."""
        return self._get(JOB_CARD_URL, params={"securityId": security_id, "lid": lid}, action="职位卡片")

    def get_job_detail(self, security_id: str, lid: str = "") -> dict[str, Any]:
        """Get detailed information for a specific job."""
        params: dict[str, str] = {"securityId": security_id}
        if lid:
            params["lid"] = lid
        return self._get(JOB_DETAIL_URL, params=params, action="职位详情")

    # ── Personal Center ─────────────────────────────────────────────

    def get_user_info(self) -> dict[str, Any]:
        """Get current user info (userId, name, avatar, etc.)."""
        return self._get(USER_INFO_URL, action="用户信息")

    def get_resume_baseinfo(self) -> dict[str, Any]:
        """Get resume basic info (full profile: name, age, degree, etc.)."""
        return self._get(RESUME_BASEINFO_URL, action="简历基本信息")

    def get_resume_expect(self) -> dict[str, Any]:
        """Get job expectations (desired position, salary, city)."""
        return self._get(RESUME_EXPECT_URL, action="求职期望")

    def get_resume_status(self) -> dict[str, Any]:
        """Get resume status."""
        return self._get(RESUME_STATUS_URL, action="简历状态")

    def get_deliver_list(self, page: int = 1) -> dict[str, Any]:
        """Get list of jobs applied to (已投递)."""
        return self._get(DELIVER_LIST_URL, params={"page": page}, action="已投递列表")

    def get_interview_data(self) -> dict[str, Any]:
        """Get interview data (面试)."""
        return self._get(INTERVIEW_DATA_URL, action="面试数据")

    def get_job_history(self, page: int = 1) -> dict[str, Any]:
        """Get job browsing history."""
        return self._get(JOB_HISTORY_URL, params={"page": page}, action="浏览历史")

    # ── Social / Chat ───────────────────────────────────────────────

    def get_friend_list(self) -> dict[str, Any]:
        """Get geek friend list (沟通过的 Boss)."""
        return self._get(FRIEND_LIST_URL, action="好友列表")

    def add_friend(self, security_id: str, lid: str = "") -> dict[str, Any]:
        """Send greeting to a Boss (打招呼 / 投递简历)."""
        params: dict[str, str] = {"securityId": security_id}
        if lid:
            params["lid"] = lid
        return self._get(FRIEND_ADD_URL, params=params, action="打招呼")

    def get_geek_job(self, security_id: str) -> dict[str, Any]:
        """Get interacted job info."""
        return self._get(GEEK_GET_JOB_URL, params={"securityId": security_id}, action="互动职位")

    def _post(self, url: str, data: dict[str, Any] | None = None, action: str = "", json_body: bool = False) -> dict[str, Any]:
        """POST request with form-encoded or JSON body, response validation, and rate-limit retry."""
        kwargs = {"json": data} if json_body else {"data": data}
        resp = self._request("POST", url, **kwargs)
        try:
            result = self._handle_response(resp, action)
            self._rate_limit_count = 0
            return result
        except RateLimitError:
            logger.info("Retrying after rate-limit cooldown...")
            resp = self._request("POST", url, **kwargs)
            result = self._handle_response(resp, action)
            self._rate_limit_count = 0
            return result

    # ── Geek Chat & Exchange ─────────────────────────────────────────

    def get_ws_auth(self) -> tuple[str, str]:
        """Return (page_token, wt2) for MQTT WebSocket authentication."""
        user_info = self._get(USER_INFO_URL, action="用户信息")
        page_token = user_info.get("token", "")
        wt_data = self._get("/wapi/zppassport/get/wt", action="WS Token")
        wt2 = wt_data.get("wt2", "")
        return page_token, wt2

    def get_geek_friend_list(self, label_id: int = 0, page: int = 1) -> dict[str, Any]:
        """Get geek chat friend list (bosses who have chatted with you)."""
        data: dict[str, Any] = {"labelId": label_id, "page": page}
        return self._post(GEEK_FRIEND_LIST_URL, data=data, action="沟通列表")

    def get_geek_last_messages(self, friend_ids: list[int]) -> list[dict[str, Any]]:
        """Get last message for each boss friend (geek perspective)."""
        ids_str = ",".join(str(fid) for fid in friend_ids)
        result = self._get(GEEK_LAST_MSG_URL, params={"friendIds": ids_str}, action="最近消息")
        return result if isinstance(result, list) else []

    def get_geek_chat_history(self, boss_id: int, count: int = 20, max_msg_id: int = 0) -> dict[str, Any]:
        """Get chat history with a specific boss (geek perspective)."""
        # historyMsg requires securityId — fetch it first
        boss_data = self.get_geek_boss_data(boss_id)
        security_id = boss_data.get("securityId", "")
        params: dict[str, Any] = {
            "gid": boss_id,
            "c": count,
            "src": 0,
            "securityId": security_id,
        }
        if max_msg_id:
            params["maxMsgId"] = max_msg_id
        return self._get(GEEK_HISTORY_MSG_URL, params=params, action="聊天记录")

    def get_geek_chat_history_all(
        self, boss_id: int, count: int = 20, max_pages: int = 50
    ) -> dict[str, Any]:
        """Get chat history with pagination, up to *count* messages.

        The underlying API requires a securityId (fetched via getBossData) and
        returns at most ~20 messages per page.  This method loops with
        ``maxMsgId`` until the requested ``count`` is reached or no more
        messages are available.
        """
        # historyMsg requires securityId — fetch it first
        boss_data = self.get_geek_boss_data(boss_id)
        security_id = boss_data.get("securityId", "")
        if not security_id:
            logger.warning("无法获取 securityId (bossId=%d)，聊天记录可能为空", boss_id)
            return {"messages": [], "total": 0}

        page_size = min(count, 20)
        all_messages: list[dict[str, Any]] = []
        max_msg_id = 0

        for _ in range(max_pages):
            params: dict[str, Any] = {
                "gid": boss_id,
                "c": page_size,
                "src": 0,
                "securityId": security_id,
            }
            if max_msg_id:
                params["maxMsgId"] = max_msg_id
            resp: dict[str, Any] = self._get(
                GEEK_HISTORY_MSG_URL, params=params, action="聊天记录"
            )
            batch = resp.get("messages", resp.get("msgList", []))
            if not batch:
                break
            all_messages.extend(batch)
            if len(all_messages) >= count:
                all_messages = all_messages[:count]
                break
            # Next page cursor — API returns minMsgId (oldest message id in batch)
            next_id = resp.get("minMsgId", 0)
            if not next_id:
                next_id = batch[-1].get("mid", batch[-1].get("msgId", batch[-1].get("id", 0)))
            if next_id == max_msg_id:
                break
            max_msg_id = next_id

        return {"messages": all_messages, "total": len(all_messages)}

    def get_geek_boss_data(self, boss_id: int) -> dict[str, Any]:
        """Get boss chat context data (securityId, encryptJobId, mobile, weixin, etc.)."""
        result = self._get("/wapi/zpchat/geek/getBossData", params={"bossId": boss_id}, action="Boss信息")
        return result.get("data", result)

    def geek_exchange_request(self, boss_id: int, security_id: str, exchange_type: int) -> dict[str, Any]:
        """Request exchange with a boss. exchange_type: 1=phone, 2=wechat, 3=resume."""
        return self._post(
            "/wapi/zpchat/exchange/request",
            data={"type": exchange_type, "bossId": boss_id, "securityId": security_id},
            action="交换请求",
        )

    def geek_send_resume(self, boss_id: int, security_id: str) -> dict[str, Any]:
        """Send resume to a boss (exchange type=3)."""
        return self.geek_exchange_request(boss_id, security_id, 3)

    def geek_request_phone(self, boss_id: int, security_id: str) -> dict[str, Any]:
        """Request phone number exchange with a boss (exchange type=1)."""
        return self.geek_exchange_request(boss_id, security_id, 1)

    def geek_request_wechat(self, boss_id: int, security_id: str) -> dict[str, Any]:
        """Request WeChat exchange with a boss (exchange type=2)."""
        return self.geek_exchange_request(boss_id, security_id, 2)

    def geek_accept_exchange(self, boss_id: int, mid: int, security_id: str = "") -> dict[str, Any]:
        """Accept an exchange request from a boss. mid: msgId from userLastMsg."""
        data: dict[str, Any] = {"bossId": boss_id, "mid": mid}
        if security_id:
            data["securityId"] = security_id
        return self._post("/wapi/zpchat/geek/acceptItemContact", data=data, action="接受交换请求")

    def geek_reject_exchange(self, boss_id: int, mid: int, security_id: str = "") -> dict[str, Any]:
        """Reject an exchange request from a boss."""
        data: dict[str, Any] = {"bossId": boss_id, "mid": mid}
        if security_id:
            data["securityId"] = security_id
        return self._post("/wapi/zpchat/geek/rejectItemContact", data=data, action="拒绝交换请求")

    def geek_accept_wechat(self, boss_id: int, mid: int, security_id: str = "") -> dict[str, Any]:
        """Accept a WeChat exchange request from a boss."""
        data: dict[str, Any] = {"bossId": boss_id, "mid": mid}
        if security_id:
            data["securityId"] = security_id
        return self._post("/wapi/zpchat/geek/acceptItemWeiXinRequest", data=data, action="接受微信交换请求")


# ── City resolution ─────────────────────────────────────────────────

def resolve_city(name: str) -> str:
    """Resolve city name to code, passthrough if already a code."""
    if name.isdigit() and len(name) >= 6:
        return name
    return CITY_CODES.get(name, CITY_CODES["全国"])


def list_cities() -> dict[str, str]:
    """Return all supported city name -> code mappings."""
    return dict(CITY_CODES)
