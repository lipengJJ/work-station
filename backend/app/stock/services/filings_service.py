"""
把 SEC submissions 接口里那一大坨并行数组（form/filingDate/items/...）整理成前端要的
披露文件列表，按类型分类，8-K 用官方 Item 编号做事件分类（不是靠猜标题关键词——8-K 每条
都自带"items"字段，比如 "5.02" 就是官方定义的"董事/高管变动"，是 SEC 自己的分类体系，
准确、不用 AI 猜）。

AI 摘要只对最近的少数几条 8-K 生成（见 ai_summary.py），不是每条都跑一遍模型——一是控制
调用成本和延迟，二是分类信息本身已经足够可靠，不需要事事都靠 AI 兜底。
"""
from __future__ import annotations

_FORM_CATEGORY_MAP: dict[str, str] = {
    "8-K": "8-K", "8-K/A": "8-K",
    "10-Q": "10-Q", "10-Q/A": "10-Q",
    "10-K": "10-K", "10-K/A": "10-K",
    "6-K": "6-K", "6-K/A": "6-K",
    "3": "Form 3", "3/A": "Form 3",
    "4": "Form 4", "4/A": "Form 4",
    "5": "Form 5", "5/A": "Form 5",
    "SC 13D": "13D", "SC 13D/A": "13D", "SCHEDULE 13D": "13D", "SCHEDULE 13D/A": "13D",
    "SC 13G": "13G", "SC 13G/A": "13G", "SCHEDULE 13G": "13G", "SCHEDULE 13G/A": "13G",
    "SC 13F": "13F", "13F-HR": "13F", "13F-HR/A": "13F", "13F-NT": "13F",
    "S-1": "S-1", "S-1/A": "S-1",
    "424B1": "424B", "424B2": "424B", "424B3": "424B", "424B4": "424B", "424B5": "424B",
}

# 8-K Item 编号 -> 中文事件分类，官方定义见 SEC Form 8-K 说明，不是关键词猜测
_ITEM_CATEGORY_MAP: dict[str, str] = {
    "1.01": "重大合同", "1.02": "重大合同终止",
    "1.03": "破产或托管风险",
    "2.01": "并购/资产处置", "2.05": "资产出售/退出成本",
    "2.02": "经营业绩/财报", "2.03": "债务和融资", "2.04": "债务和融资",
    "2.06": "重大资产减值",
    "3.01": "退市风险", "3.02": "股权非公开发行",
    "3.03": "证券权利重大变更",
    "4.01": "会计师变更", "4.02": "财务重述",
    "5.01": "控制权变化", "5.02": "管理层变动",
    "5.03": "章程修订", "5.07": "股东投票结果",
    "7.01": "监管公平披露(FD)", "8.01": "其他重大事项", "9.01": "财务报表及附件",
}

_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
_MATERIAL_ITEM_CODES = {"1.01", "1.02", "1.03", "2.01", "2.03", "2.04", "2.05", "2.06", "3.01", "4.01", "4.02", "5.01", "5.02"}


def _filing_url(cik: int, accession_no: str, primary_document: str) -> str:
    accession_no_dashes = accession_no.replace("-", "")
    return f"{_ARCHIVES_BASE}/{cik}/{accession_no_dashes}/{primary_document}"


def classify_8k_items(items: str) -> list[str]:
    if not items:
        return []
    codes = [c.strip() for c in items.split(",") if c.strip()]
    return [_ITEM_CATEGORY_MAP.get(c, f"Item {c}") for c in codes]


def is_material_8k(items: str) -> bool:
    codes = {c.strip() for c in (items or "").split(",") if c.strip()}
    return bool(codes & _MATERIAL_ITEM_CODES)


def list_filings(submissions: dict, cik: int, limit: int = 200) -> list[dict]:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    accession_numbers = recent.get("accessionNumber", [])
    primary_documents = recent.get("primaryDocument", [])
    primary_descriptions = recent.get("primaryDocDescription", [])
    items_list = recent.get("items", [])

    results = []
    for i in range(min(len(forms), limit)):
        form = forms[i]
        category = _FORM_CATEGORY_MAP.get(form, "其他")
        accession_no = accession_numbers[i]
        primary_document = primary_documents[i] if i < len(primary_documents) else ""
        items = items_list[i] if i < len(items_list) else ""

        record = {
            "form": form,
            "category": category,
            "filed_at": filing_dates[i] if i < len(filing_dates) else None,
            "financial_period": report_dates[i] if i < len(report_dates) else None,
            "accession_number": accession_no,
            "is_amendment": form.endswith("/A"),
            "primary_document": primary_document,
            "description": primary_descriptions[i] if i < len(primary_descriptions) else None,
            "url": _filing_url(cik, accession_no, primary_document) if primary_document else None,
            "index_url": f"{_ARCHIVES_BASE}/{cik}/{accession_no.replace('-', '')}/{accession_no}-index.htm",
        }
        if form.startswith("8-K"):
            record["event_categories"] = classify_8k_items(items)
            record["is_material"] = is_material_8k(items)
        results.append(record)

    return results


def group_by_category(filings: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for f in filings:
        grouped.setdefault(f["category"], []).append(f)
    return grouped
