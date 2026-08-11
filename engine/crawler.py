#!/usr/bin/env python3
"""
双色球数据爬虫 —— 从 500.com 拉取全量/增量开奖数据

字段格式与 data/ssq_all.json 保持一致:
  期号, 红球1~6, 蓝球, 快乐星期天, 奖池奖金, 一/二等奖注数与奖金, 总投注额, 开奖日期
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Callable, Optional

import requests
from bs4 import BeautifulSoup

from config import FETCH_LIMIT, FETCH_RETRIES, FETCH_TIMEOUT, SSQ_URL, USER_AGENT

# 500.com 双色球 history 表固定 16 列
_DATA_COLS = 16


def _parse_int(value: str) -> Optional[int]:
    if value is None:
        return None
    value = value.strip().replace(",", "").replace(" ", "")
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_date(value: str) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return value
    for fmt in ("%Y/%m/%d", "%Y%m%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value


def _clean_cell(td) -> str:
    text = td.get_text().strip()
    return text.replace("\xa0", "").replace("\u3000", "")


def _validate_row(row: dict) -> bool:
    """校验单期红蓝球范围与互异性"""
    reds = []
    for i in range(1, 7):
        v = row.get(f"红球{i}")
        if v is None or not (1 <= v <= 33):
            return False
        reds.append(v)
    if len(set(reds)) != 6:
        return False
    blue = row.get("蓝球")
    if blue is None or not (1 <= blue <= 16):
        return False
    issue = row.get("期号", "")
    if not str(issue).isdigit() or len(str(issue)) < 5:
        return False
    return True


def fetch_ssq_data(
    limit: int = None,
    sort: int = 1,
    max_retries: int = None,
    timeout: int = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> list[dict]:
    """
    从 500.com 获取双色球历史数据。

    Args:
        limit: 拉取期数上限 (默认 config.FETCH_LIMIT)
        sort: 0=最新在前, 1=最早在前
        max_retries / timeout: 网络参数
        progress_callback: 进度日志回调

    Returns:
        list[dict]: 标准字段的期数据；失败返回空列表
    """
    limit = limit if limit is not None else FETCH_LIMIT
    max_retries = max_retries if max_retries is not None else FETCH_RETRIES
    timeout = timeout if timeout is not None else FETCH_TIMEOUT

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    params = {"limit": limit, "sort": sort}

    def log(msg: str):
        if progress_callback:
            progress_callback(msg)
        else:
            print(f"  {msg}")

    for attempt in range(1, max_retries + 1):
        log(f"请求 500.com 双色球数据… ({attempt}/{max_retries})")
        try:
            resp = requests.get(SSQ_URL, params=params, headers=headers, timeout=timeout)
            resp.encoding = "utf-8"
            if resp.status_code != 200:
                log(f"请求失败 status={resp.status_code}")
                if attempt < max_retries:
                    time.sleep(3 * attempt)
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.find("table", id="tablelist") or soup.find("table")
            if not table:
                log("未找到数据表格")
                continue

            rows_raw = []
            for tr in table.find_all("tr"):
                tds = tr.find_all("td")
                if len(tds) == _DATA_COLS:
                    rows_raw.append(tds)

            if not rows_raw:
                log(f"未找到 {_DATA_COLS} 列数据行")
                continue

            results = []
            parse_errors = 0
            for idx, tds in enumerate(rows_raw):
                try:
                    issue = _clean_cell(tds[0])
                    if not issue.isdigit() or len(issue) < 5:
                        continue

                    # 红球升序存放，与历史 JSON 一致
                    reds = sorted(
                        _parse_int(_clean_cell(tds[i])) for i in range(1, 7)
                    )
                    if any(r is None for r in reds):
                        parse_errors += 1
                        continue

                    row = {
                        "期号": issue,
                        "红球1": reds[0],
                        "红球2": reds[1],
                        "红球3": reds[2],
                        "红球4": reds[3],
                        "红球5": reds[4],
                        "红球6": reds[5],
                        "蓝球": _parse_int(_clean_cell(tds[7])),
                        "快乐星期天": _parse_int(_clean_cell(tds[8])),
                        "奖池奖金": _parse_int(_clean_cell(tds[9])),
                        "一等奖注数": _parse_int(_clean_cell(tds[10])),
                        "一等奖奖金": _parse_int(_clean_cell(tds[11])),
                        "二等奖注数": _parse_int(_clean_cell(tds[12])),
                        "二等奖奖金": _parse_int(_clean_cell(tds[13])),
                        "总投注额": _parse_int(_clean_cell(tds[14])),
                        "开奖日期": _parse_date(_clean_cell(tds[15])),
                    }
                    # 缺失奖金/投注时兜底为 0，避免下游特征计算崩溃
                    for k in (
                        "奖池奖金", "一等奖注数", "一等奖奖金",
                        "二等奖注数", "二等奖奖金", "总投注额",
                    ):
                        if row[k] is None:
                            row[k] = 0

                    if _validate_row(row):
                        results.append(row)
                    else:
                        parse_errors += 1
                except Exception as e:
                    parse_errors += 1
                    if parse_errors <= 3:
                        log(f"第 {idx} 行解析异常: {e}")

            if not results:
                log("解析完成后无有效数据")
                continue

            # 按期号排序（升序）
            results.sort(key=lambda r: int(r["期号"]))
            # 去重（保留后出现的，通常字段更完整）
            by_issue = {r["期号"]: r for r in results}
            results = sorted(by_issue.values(), key=lambda r: int(r["期号"]))

            log(
                f"爬取完成: {len(results)} 期，"
                f"{results[0]['期号']}~{results[-1]['期号']}，"
                f"解析跳过 {parse_errors} 行"
            )
            return results

        except requests.exceptions.Timeout:
            log(f"请求超时 (第 {attempt} 次)")
            if attempt < max_retries:
                time.sleep(5 * attempt)
        except requests.exceptions.ConnectionError as e:
            log(f"连接错误: {e}")
            if attempt < max_retries:
                time.sleep(5 * attempt)
        except Exception as e:
            log(f"未知错误: {e}")
            import traceback
            traceback.print_exc()
            break

    return []
