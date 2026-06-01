import os
import smtplib
import requests
import xml.etree.ElementTree as ET
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta

# ── 配置 ──────────────────────────────────────────────
EMAIL_FROM = os.environ["EMAIL_FROM"]       # 163邮箱
EMAIL_TO   = os.environ["EMAIL_TO"]         # 收件人
EMAIL_PASS = os.environ["EMAIL_PASS"]       # 163授权码
SMTP_HOST  = "smtp.163.com"
SMTP_PORT  = 465

KEYWORDS = {
    "RAG / LLM": [
        "retrieval augmented generation",
        "large language model",
        "RAG LLM",
    ],
    "生物统计 / 临床试验": [
        "biostatistics",
        "adaptive clinical trial",
        "clinical trial design",
        "adaptive design",
    ],
}
# ──────────────────────────────────────────────────────


def fetch_arxiv(query: str, max_results: int = 5) -> list[dict]:
    """从 ArXiv 抓取论文"""
    url = "https://export.arxiv.org/api/query"
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    resp = requests.get(url, params=params, timeout=15)
    if resp.status_code != 200:
        return []

    root = ET.fromstring(resp.text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    papers = []
    yesterday = datetime.utcnow() - timedelta(days=1)

    for entry in root.findall("atom:entry", ns):
        published_str = entry.find("atom:published", ns).text[:10]
        published = datetime.strptime(published_str, "%Y-%m-%d")
        if published < yesterday:
            continue
        papers.append({
            "title":    entry.find("atom:title", ns).text.strip(),
            "authors":  ", ".join(
                a.find("atom:name", ns).text
                for a in entry.findall("atom:author", ns)[:3]
            ),
            "summary":  entry.find("atom:summary", ns).text.strip()[:300] + "...",
            "link":     entry.find("atom:id", ns).text.strip(),
            "date":     published_str,
        })
    return papers


def fetch_pubmed(query: str, max_results: int = 5) -> list[dict]:
    """从 PubMed 抓取论文"""
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y/%m/%d")
    today     = datetime.utcnow().strftime("%Y/%m/%d")

    # 搜索
    search = requests.get(f"{base}/esearch.fcgi", params={
        "db": "pubmed", "term": query,
        "mindate": yesterday, "maxdate": today,
        "datetype": "pdat", "retmax": max_results,
        "retmode": "json",
    }, timeout=15)
    if search.status_code != 200:
        return []

    ids = search.json().get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []

    # 获取详情
    fetch = requests.get(f"{base}/efetch.fcgi", params={
        "db": "pubmed", "id": ",".join(ids),
        "retmode": "xml", "rettype": "abstract",
    }, timeout=15)
    if fetch.status_code != 200:
        return []

    root = ET.fromstring(fetch.text)
    papers = []
    for article in root.findall(".//PubmedArticle"):
        title = article.findtext(".//ArticleTitle", "N/A")
        abstract = article.findtext(".//AbstractText", "N/A")
        if abstract != "N/A":
            abstract = abstract[:300] + "..."
        authors = [
            f"{a.findtext('LastName', '')} {a.findtext('ForeName', '')}".strip()
            for a in article.findall(".//Author")[:3]
        ]
        pmid = article.findtext(".//PMID", "")
        papers.append({
            "title":   title,
            "authors": ", ".join(authors),
            "summary": abstract,
            "link":    f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "date":    today,
        })
    return papers


def build_html(all_papers: dict) -> str:
    """生成HTML邮件内容"""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    total = sum(len(v) for v in all_papers.values())

    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:800px;margin:auto;padding:20px;">
    <h1 style="color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:10px;">
        📚 每日论文推送 · {today}
    </h1>
    <p style="color:#7f8c8d;">今日共找到 <strong>{total}</strong> 篇新文章</p>
    """

    if total == 0:
        html += "<p style='color:#e74c3c;'>今日暂无新文章，明天继续！</p>"
    else:
        for category, papers in all_papers.items():
            if not papers:
                continue
            html += f"""
            <h2 style="color:#2980b9;margin-top:30px;">
                🔬 {category} ({len(papers)} 篇)
            </h2>"""
            for p in papers:
                html += f"""
                <div style="background:#f8f9fa;border-left:4px solid #3498db;
                            padding:15px;margin:15px 0;border-radius:4px;">
                    <h3 style="margin:0 0 8px;color:#2c3e50;font-size:16px;">
                        <a href="{p['link']}" style="color:#2c3e50;text-decoration:none;">
                            {p['title']}
                        </a>
                    </h3>
                    <p style="color:#7f8c8d;margin:4px 0;font-size:13px;">
                        👥 {p['authors']} · 📅 {p['date']}
                    </p>
                    <p style="color:#555;font-size:14px;margin:8px 0 0;">
                        {p['summary']}
                    </p>
                    <a href="{p['link']}" style="color:#3498db;font-size:13px;">
                        阅读全文 →
                    </a>
                </div>"""

    html += """
    <hr style="margin-top:40px;border:none;border-top:1px solid #eee;">
    <p style="color:#bdc3c7;font-size:12px;text-align:center;">
        由 GitHub Actions 自动推送 · 每日 UTC 08:00 运行
    </p>
    </body></html>"""
    return html


def send_email(html: str):
    """发送邮件"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📚 每日论文推送 · {datetime.utcnow().strftime('%Y-%m-%d')}"
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(EMAIL_FROM, EMAIL_PASS)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
    print("✅ 邮件发送成功")


def main():
    all_papers = {}
    for category, keywords in KEYWORDS.items():
        papers = []
        for kw in keywords:
            papers += fetch_arxiv(kw, max_results=3)
            papers += fetch_pubmed(kw, max_results=3)
        # 去重（按标题）
        seen = set()
        unique = []
        for p in papers:
            if p["title"] not in seen:
                seen.add(p["title"])
                unique.append(p)
        all_papers[category] = unique[:8]  # 每类最多8篇

    html = build_html(all_papers)
    send_email(html)


if __name__ == "__main__":
    main()
