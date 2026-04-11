from __future__ import annotations

import html
import re
from typing import Any

import httpx
from pydantic import BaseModel, Field

from feishubot.ai.tools.base import Tool


class WebSearchArguments(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    max_results: int = Field(default=5, ge=1, le=10)
    timeout_seconds: float = Field(default=15.0, gt=0, le=60)


class WebSearchTool(Tool):
    name = "web_search"
    description = "Search web content and return snippets with source links."
    args_model = WebSearchArguments

    @staticmethod
    def _append_result(
        results: list[dict[str, str]],
        *,
        title: str,
        snippet: str,
        url: str,
        max_results: int,
    ) -> None:
        if len(results) >= max_results:
            return
        title_clean = title.strip()
        snippet_clean = snippet.strip()
        url_clean = url.strip()
        if not (title_clean or snippet_clean) or not url_clean:
            return
        results.append(
            {
                "title": title_clean or "(untitled)",
                "snippet": snippet_clean,
                "url": url_clean,
            }
        )

    def _extract_results(self, data: dict[str, Any], *, max_results: int) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []

        self._append_result(
            results,
            title=str(data.get("Heading", "")),
            snippet=str(data.get("AbstractText", "")),
            url=str(data.get("AbstractURL", "")),
            max_results=max_results,
        )

        related_topics = data.get("RelatedTopics", [])
        if isinstance(related_topics, list):
            for item in related_topics:
                if len(results) >= max_results:
                    break

                if isinstance(item, dict) and isinstance(item.get("Topics"), list):
                    for nested in item["Topics"]:
                        if len(results) >= max_results:
                            break
                        if isinstance(nested, dict):
                            self._append_result(
                                results,
                                title=str(nested.get("Text", "")).split(" - ", 1)[0],
                                snippet=str(nested.get("Text", "")),
                                url=str(nested.get("FirstURL", "")),
                                max_results=max_results,
                            )
                    continue

                if isinstance(item, dict):
                    self._append_result(
                        results,
                        title=str(item.get("Text", "")).split(" - ", 1)[0],
                        snippet=str(item.get("Text", "")),
                        url=str(item.get("FirstURL", "")),
                        max_results=max_results,
                    )

        return results

    def _extract_bing_rss_results(self, rss_text: str, *, max_results: int) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        item_pattern = re.compile(r"<item>(.*?)</item>", flags=re.IGNORECASE | re.DOTALL)
        title_pattern = re.compile(r"<title>(.*?)</title>", flags=re.IGNORECASE | re.DOTALL)
        desc_pattern = re.compile(
            r"<description>(.*?)</description>",
            flags=re.IGNORECASE | re.DOTALL,
        )
        link_pattern = re.compile(r"<link>(.*?)</link>", flags=re.IGNORECASE | re.DOTALL)

        for item_xml in item_pattern.findall(rss_text):
            if len(results) >= max_results:
                break

            title_match = title_pattern.search(item_xml)
            desc_match = desc_pattern.search(item_xml)
            link_match = link_pattern.search(item_xml)

            title = html.unescape(title_match.group(1).strip()) if title_match else ""
            snippet = html.unescape(desc_match.group(1).strip()) if desc_match else ""
            url = html.unescape(link_match.group(1).strip()) if link_match else ""
            self._append_result(
                results,
                title=title,
                snippet=snippet,
                url=url,
                max_results=max_results,
            )

        return results

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query", "")).strip()
        max_results = int(arguments.get("max_results", 5))
        timeout_seconds = float(arguments.get("timeout_seconds", 15.0))
        headers = {"User-Agent": "feishubot/0.1.0 (+https://github.com/wsmxd/feishubot)"}

        errors: list[str] = []

        ddg_params = {
            "q": query,
            "format": "json",
            "no_redirect": "1",
            "no_html": "1",
            "skip_disambig": "1",
        }

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            try:
                ddg_response = await client.get(
                    "https://api.duckduckgo.com/", params=ddg_params, headers=headers
                )
                ddg_response.raise_for_status()
                ddg_payload = ddg_response.json()
                if not isinstance(ddg_payload, dict):
                    raise RuntimeError("invalid duckduckgo response")

                ddg_results = self._extract_results(ddg_payload, max_results=max_results)
                if ddg_results:
                    return {
                        "provider": "duckduckgo_instant",
                        "query": query,
                        "result_count": len(ddg_results),
                        "results": ddg_results,
                    }
                errors.append("duckduckgo returned 0 results")
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                errors.append(f"duckduckgo failed: {exc}")

            try:
                bing_response = await client.get(
                    "https://cn.bing.com/search",
                    params={"q": query, "format": "rss"},
                    headers=headers,
                )
                bing_response.raise_for_status()
                bing_results = self._extract_bing_rss_results(
                    bing_response.text,
                    max_results=max_results,
                )
                if bing_results:
                    return {
                        "provider": "bing_rss",
                        "query": query,
                        "result_count": len(bing_results),
                        "results": bing_results,
                        "fallback_used": True,
                        "notes": errors,
                    }
                errors.append("bing_rss returned 0 results")
            except httpx.HTTPError as exc:
                errors.append(f"bing_rss failed: {exc}")

        return {
            "provider": "unavailable",
            "query": query,
            "result_count": 0,
            "results": [],
            "notes": errors,
        }
