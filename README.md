# 📚 每日论文推送

每天自动从 ArXiv 和 PubMed 抓取最新论文，发送到邮箱。

## 覆盖领域
- RAG / LLM（检索增强生成、大语言模型）
- 生物统计 / 临床试验 / 适应性设计

## 配置步骤

### 1. 获取163邮箱授权码
1. 登录 163.com → 设置 → POP3/SMTP/IMAP
2. 开启 SMTP 服务
3. 获取**授权码**（不是邮箱密码）

### 2. 配置 GitHub Secrets
在你的 GitHub 仓库 → Settings → Secrets → Actions → New repository secret，添加：

| Secret 名称 | 值 |
|------------|-----|
| `EMAIL_FROM` | 你的163邮箱（如 xxx@163.com） |
| `EMAIL_TO` | 收件邮箱（如 xxx@163.com） |
| `EMAIL_PASS` | 163邮箱授权码 |

### 3. 启用 Actions
仓库 → Actions → 启用 Workflows

### 4. 手动测试
Actions → 每日论文推送 → Run workflow

## 运行时间
每天 UTC 08:00（北京时间 16:00）自动运行
