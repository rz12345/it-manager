"""Playwright + CSS/Regex/JS 擷取工具（email 任務動態變數來源）。

自 task-manager 原樣移植。
"""
import hashlib
import re

from bs4 import BeautifulSoup


_MAX_CONTENT = 10_000


def fetch_with_playwright(url: str, timeout_ms: int = 30_000) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout_ms, wait_until='networkidle')
            html = page.content()
        finally:
            browser.close()
    return html


def extract_by_js(url: str, js_snippet: str, timeout_ms: int = 60_000) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout_ms, wait_until='domcontentloaded')
            result = page.evaluate(js_snippet)
        finally:
            browser.close()

    if result is None:
        raise ValueError('JS 擷取結果為 None')
    text = str(result).strip()
    if not text:
        raise ValueError('JS 擷取結果為空')
    return text


def extract_by_css(html: str, selector: str) -> str:
    soup = BeautifulSoup(html, 'lxml')
    el = soup.select_one(selector)
    if el is None:
        raise ValueError(f'CSS selector 未匹配到任何元素: {selector!r}')
    text = el.get_text(separator=' ', strip=True)
    if not text:
        raise ValueError(f'CSS selector 匹配到元素但內容為空: {selector!r}')
    return text


def extract_by_regex(html: str, pattern: str) -> str:
    m = re.search(pattern, html, re.DOTALL)
    if m is None:
        raise ValueError(f'Regex 未匹配到任何內容: {pattern!r}')
    text = m.group(1) if m.lastindex else m.group(0)
    text = text.strip()
    if not text:
        raise ValueError(f'Regex 匹配到內容但結果為空: {pattern!r}')
    return text


def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def truncate(text: str) -> str:
    if len(text) > _MAX_CONTENT:
        return text[:_MAX_CONTENT] + f'\n… (截斷，原長 {len(text)} 字)'
    return text


def scrape_and_extract(url: str, extract_type: str, extract_pattern: str) -> tuple:
    if extract_type == 'js':
        text = extract_by_js(url, extract_pattern)
    else:
        html = fetch_with_playwright(url)
        if extract_type == 'css':
            text = extract_by_css(html, extract_pattern)
        else:
            text = extract_by_regex(html, extract_pattern)

    text = truncate(text)
    return text, compute_hash(text)
