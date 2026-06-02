import os
import smtplib
import requests
import xml.etree.ElementTree as ET
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta

# ── 配置 ──────────────────────────────────────────────
EMAIL_FROM    = os.environ["EMAIL_FROM"]
EMAIL_TO      = os.environ["EMAIL_TO"]
EMAIL_PASS    = os.environ["EMAIL_PASS"]
ZOTERO_KEY    = os.environ["ZOTERO_API_KEY"]
ZOTERO_UID    = os.environ["ZOTERO_USER_ID"]
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

SMTP_HOST = "smtp.163.com"
SMTP_PORT = 465

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
        abstract = entry.find("atom:summary", ns).text.strip()
        papers.append({
            "title":    entry.find("atom:title", ns).text.strip(),
            "authors":  ", ".join(
                a.find("atom:name", ns).text
                for a in entry.findall("atom:author", ns)[:3]
            ),
            "abstract": abstract,
            "summary":  abstract[:300] + "...",
            "link":     entry.find("atom:id", ns).text.strip(),
            "date":     published_str,
            "source":   "arxiv",
        })
    return papers


def fetch_pubmed(query: str, max_results: int = 5) -> list[dict]:
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y/%m/%d")
    today     = datetime.utcnow().strftime("%Y/%m/%d")

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

    fetch = requests.get(f"{base}/efetch.fcgi", params={
        "db": "pubmed", "id": ",".join(ids),
        "retmode": "xml", "rettype": "abstract",
    }, timeout=15)
    if fetch.status_code != 200:
        return []

    root = ET.fromstring(fetch.text)
    papers = []
    for article in root.findall(".//PubmedArticle"):
        title    = article.findtext(".//ArticleTitle", "N/A")
        abstract = article.findtext(".//AbstractText", "N/A")
        authors  = [
            f"{a.findtext('LastName', '')} {a.findtext('ForeName', '')}".strip()
            for a in article.findall(".//Author")[:3]
        ]
        pmid = article.findtext(".//PMID", "")
        papers.append({
            "title":    title,
            "authors":  ", ".join(authors),
            "abstract": abstract,
            "summary":  abstract[:300] + "..." if abstract != "N/A" else "N/A",
            "link":     f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "date":     today,
            "source":   "pubmed",
            "pmid":     pmid,
        })
    return papers


def ai_annotate(paper: dict) -> str:
    """用 Claude 生成中文批注"""
    if not ANTHROPIC_KEY:
        return "（未配置 ANTHROPIC_API_KEY，跳过 AI 批注）"

    prompt = f"""你是一位生物统计和AI领域的博士生导师。
请用中文对以下论文写一段简短批注（100字以内），包括：
1. 核心贡献一句话
2. 与RAG/LLM/生物统计/临床试验的相关度（高/中/低）
3. 是否值得精读（是/否）及理由

论文标题：{paper['title']}
摘要：{paper['abstract'][:500]}"""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",,
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        return resp.json()["content"][0]["text"]
    except Exception as e:
        return f"AI批注失败: {e}"


def save_to_zotero(paper: dict, category: str, annotation: str) -> bool:
    """保存论文到 Zotero，并附上 AI 批注"""
    url = f"https://api.zotero.org/users/{ZOTERO_UID}/items"
    headers = {
        "Zotero-API-Key": ZOTERO_KEY,
        "Content-Type": "application/json",
    }

    # 构建 Zotero item
    if paper["source"] == "arxiv":
        item_type = "preprint"
        repo = "arXiv"
    else:
        item_type = "journalArticle"
        repo = "PubMed"

    item = {
        "itemType": item_type,
        "title": paper["title"],
        "creators": [
            {"creatorType": "author", "name": a.strip()}
            for a in paper["authors"].split(",")
        ],
        "abstractNote": paper["abstract"],
        "url": paper["link"],
        "date": paper["date"],
        "repository": repo,
        "tags": [
            {"tag": category},
            {"tag": "auto-imported"},
            {"tag": "daily-paper"},
        ],
        "note": f"【AI批注】\n{annotation}\n\n【导入时间】{datetime.utcnow().strftime('%Y-%m-%d')}",
    }

    try:
        resp = requests.post(url, headers=headers, json=[item], timeout=15)
        return resp.status_code in (200, 201)
    except Exception:
        return False


def build_html(all_papers: dict, annotations: dict) -> str:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    total = sum(len(v) for v in all_papers.values())

    html = f"""
    <html><body style="font-family:Arial,sans-serif;max-width:800px;margin:auto;padding:20px;">
    <h1 style="color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:10px;">
        📚 每日论文推送 · {today}
    </h1>
    <p style="color:#7f8c8d;">今日共找到 <strong>{total}</strong> 篇新文章，已自动保存至 Zotero</p>
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
                ann = annotations.get(p["title"], "")
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
                    <p style="color:#555;font-size:14px;margin:8px 0;">
                        {p['summary']}
                    </p>
                    {"" if not ann else f'<div style="background:#eaf4fb;border-left:3px solid #2980b9;padding:10px;margin-top:8px;border-radius:3px;font-size:13px;color:#2c3e50;"><strong>🤖 AI批注：</strong><br>{ann}</div>'}
                    <a href="{p['link']}" style="color:#3498db;font-size:13px;">
                        阅读全文 →
                    </a>
                </div>"""

    html += """
    <hr style="margin-top:40px;border:none;border-top:1px solid #eee;">
    <p style="color:#bdc3c7;font-size:12px;text-align:center;">
        由 GitHub Actions 自动推送 · 每日 UTC 08:00（北京时间 16:00）运行
    </p>
    </body></html>"""
    return html


def send_email(html: str):
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
    # 1. 抓取文章
    all_papers = {}
    for category, keywords in KEYWORDS.items():
        papers = []
        for kw in keywords:
            papers += fetch_arxiv(kw, max_results=3)
            papers += fetch_pubmed(kw, max_results=3)
        # 去重
        seen, unique = set(), []
        for p in papers:
            if p["title"] not in seen:
                seen.add(p["title"])
                unique.append(p)
        all_papers[category] = unique[:8]

    # 2. AI 批注 + 保存到 Zotero
    annotations = {}
    for category, papers in all_papers.items():
        for p in papers:
            print(f"处理：{p['title'][:50]}...")
            ann = ai_annotate(p)
            annotations[p["title"]] = ann
            ok = save_to_zotero(p, category, ann)
            print(f"  Zotero: {'✅' if ok else '❌'}  AI批注: {'✅' if ann else '❌'}")

    # 3. 发送邮件
    html = build_html(all_papers, annotations)
    send_email(html)
    print("🎉 全部完成")


if __name__ == "__main__":
    main()
