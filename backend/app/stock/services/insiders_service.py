"""
Form 4（内部人交易）解析：submissions 接口只给"有一份 Form 4"这个事实，具体谁、买卖多少股、
什么价格要去拉那份 Form 4 自己的 XML 原始数据文件解析。primaryDocument 字段给的是 XSL
渲染过的"好看"版本路径（比如 "xslF345X06/form4.xml"），真正的结构化数据在同一个目录下
去掉 xsl 子目录前缀的那个文件（实测 AAPL 一份 Form 4 验证过这个规律）。

按官方交易代码区分"主动买卖 vs 股权激励/行权/税务处置"，不是把所有内部人交易都当利好/
利空一锅端——公开市场主动买入（P）单独标出来，这才是真正值得关注的信号。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.stock.services import sec_client

# SEC 官方 Form 4 交易代码定义（Table II Instructions），不是猜的
_TRANSACTION_CODE_LABELS: dict[str, str] = {
    "P": "公开市场买入", "S": "公开市场卖出",
    "A": "股权激励授予", "M": "期权行权/衍生品转换", "F": "税务代扣处置",
    "G": "赠予", "C": "可转换证券转换", "X": "期权行权",
    "D": "处置给发行人", "I": "利益关联处置",
    "J": "其他(需查看脚注)", "K": "衡平法留置权", "L": "小额豁免交易",
    "U": "要约收购中处置", "W": "遗嘱/继承取得", "Z": "信托相关",
    "H": "期权到期", "O": "行使不属于第16(b)条的衍生品",
    "E": "对发行人的义务清偿", "N": "非市场自主处置",
}

_TRANSACTION_CATEGORY: dict[str, str] = {
    "P": "公开市场主动买入", "S": "公开市场卖出",
    "A": "股权激励", "M": "期权行权", "F": "税务处置",
    "G": "赠予", "X": "期权行权",
}


def classify_transaction(code: str) -> dict:
    return {
        "code": code,
        "label": _TRANSACTION_CODE_LABELS.get(code, f"其他({code})"),
        "category": _TRANSACTION_CATEGORY.get(code, "其他"),
        "is_open_market_buy": code == "P",
    }


def _raw_xml_filename(primary_document: str) -> str:
    return primary_document.split("/")[-1]


def _text(el: Optional[ET.Element]) -> Optional[str]:
    if el is None or el.text is None:
        return None
    return el.text.strip() or None


def _value(parent: ET.Element, tag: str) -> Optional[str]:
    node = parent.find(tag)
    if node is None:
        return None
    value_node = node.find("value")
    return _text(value_node) if value_node is not None else _text(node)


def _parse_transactions(root: ET.Element, table_tag: str, txn_tag: str, derivative: bool) -> list[dict]:
    out = []
    table = root.find(table_tag)
    if table is None:
        return out
    for txn in table.findall(txn_tag):
        coding = txn.find("transactionCoding")
        amounts = txn.find("transactionAmounts")
        post = txn.find("postTransactionAmounts")
        ownership = txn.find("ownershipNature")

        code = _value(coding, "transactionCode") if coding is not None else None
        shares = _value(amounts, "transactionShares") if amounts is not None else None
        price = _value(amounts, "transactionPricePerShare") if amounts is not None else None
        acquired_disposed = _value(amounts, "transactionAcquiredDisposedCode") if amounts is not None else None
        shares_after = _value(post, "sharesOwnedFollowingTransaction") if post is not None else None

        out.append(
            {
                "security_title": _value(txn, "securityTitle"),
                "transaction_date": _value(txn, "transactionDate"),
                "transaction_code": code,
                **classify_transaction(code or ""),
                "shares": float(shares) if shares else None,
                "price_per_share": float(price) if price else None,
                "acquired_or_disposed": acquired_disposed,
                "shares_owned_after": float(shares_after) if shares_after else None,
                "direct_or_indirect": _value(ownership, "directOrIndirectOwnership") if ownership is not None else None,
                "is_derivative": derivative,
            }
        )
    return out


def parse_form4_xml(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)

    issuer = root.find("issuer")
    owner = root.find("reportingOwner")
    owner_id = owner.find("reportingOwnerId") if owner is not None else None
    relationship = owner.find("reportingOwnerRelationship") if owner is not None else None

    non_derivative = _parse_transactions(root, "nonDerivativeTable", "nonDerivativeTransaction", derivative=False)
    derivative = _parse_transactions(root, "derivativeTable", "derivativeTransaction", derivative=True)

    return {
        "issuer_symbol": _value(issuer, "issuerTradingSymbol") if issuer is not None else None,
        "owner_name": _text(owner_id.find("rptOwnerName")) if owner_id is not None else None,
        "is_officer": (_text(relationship.find("isOfficer")) if relationship is not None else None) == "true",
        "is_director": (_text(relationship.find("isDirector")) if relationship is not None else None) == "true",
        "is_ten_percent_owner": (_text(relationship.find("isTenPercentOwner")) if relationship is not None else None) == "true",
        "officer_title": _text(relationship.find("officerTitle")) if relationship is not None else None,
        "period_of_report": _value(root, "periodOfReport"),
        "transactions": non_derivative + derivative,
    }


def get_insider_transactions(db: Session, cik: int, cik_str: str, form4_filings: list[dict], limit: int = 15) -> tuple[list[dict], list[str]]:
    """form4_filings 是 filings_service.list_filings 结果里 category=='Form 4' 的那些，
    按 filed_at 已经是最新在前——取最近 limit 份分别拉 XML 解析。单份解析失败不影响其它份。"""
    results = []
    failures = []
    for filing in form4_filings[:limit]:
        try:
            xml_filename = _raw_xml_filename(filing["primary_document"])
            xml_text = sec_client.fetch_filing_document(db, cik, filing["accession_number"], xml_filename)
            parsed = parse_form4_xml(xml_text)
            parsed["filed_at"] = filing["filed_at"]
            parsed["accession_number"] = filing["accession_number"]
            parsed["index_url"] = filing["index_url"]
            results.append(parsed)
        except Exception as e:
            logger.warning(f"解析 Form 4 失败 accession={filing.get('accession_number')}: {e}")
            failures.append(str(filing.get("accession_number")))
    return results, failures
