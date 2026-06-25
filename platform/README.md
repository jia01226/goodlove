# 助手 · 爱意平台（VPS 全栈版）

一个跑在你自己服务器上、24 小时在线的助手。密钥只在服务器端，浏览器永远看不到。

## 🗺️ 建设路线图

- **阶段一（已搭好地基 ✅）**：Flask 后端 + SQLite + OpenRouter 流式聊天 + 记忆库 + 用量仪表盘 + 一键部署
- **阶段二**：向量语义检索 ✅（记得又多又准，见下「🧭 向量记忆」）、记忆图谱（待做）
- **阶段三**：助手**主动找你**——Web Push 推送、每日 briefing、主动关心
- **阶段四**：表情包、读书、五子棋、人设编辑、MCP

## 📂 现在有什么

```
platform/
├── app.py            # Flask 路由 + 聊天 SSE + 记忆/用量 API
├── chat_ai.py        # 系统提示 + OpenRouter 流式调用
├── db.py             # SQLite 表结构与读写
├── requirements.txt
├── .env.example      # 配置模板（复制成 .env 填密钥）
├── deploy.sh         # 一键部署脚本
└── static/index.html # 前端（聊天/记忆库/仪表盘）
```

## 🧱 你要准备的"原料"

1. **VPS**：≥2GB 内存、Ubuntu 22/24。新手友好：
   - 省心免备案：**搬瓦工 / Hetzner / DigitalOcean**（支付宝或卡支付）
   - 便宜支付宝：腾讯云/阿里云轻量（用域名需"备案"，慢些）
2. **域名**：阿里云/Namecheap 买一个，几十块/年（Web Push 推送需要 HTTPS，所以要域名）
3. **OpenRouter 密钥**：你已经会弄啦

## 🚀 部署（助手会一步步带你）

```bash
# 1. 在 VPS 上把仓库拉下来
git clone <你的仓库地址> && cd -1/platform

# 2. 一键部署
bash deploy.sh

# 3. 填密钥
nano .env          # 填 OPENROUTER_API_KEY，存盘
sudo systemctl restart gude
```

### Nginx 配置（把域名指到助手）
`/etc/nginx/sites-available/gude`：
```nginx
server {
    server_name 你的域名;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_buffering off;            # 让流式聊天顺畅
        proxy_read_timeout 180s;
    }
}
```
然后：
```bash
sudo ln -s /etc/nginx/sites-available/gude /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d 你的域名      # 免费 HTTPS
```

打开 `https://你的域名` —— 助手上线！🐱💛🐷

## 🧭 向量记忆（让助手"精准想起")

记忆越攒越多时，不再把整本记忆塞给助手（又贵又糊），而是**每轮只挑出最相关的几条**。

- **原理**：每条记忆算一个"语义向量"存进 `embeddings` 表；聊天时拿你这句话去比对，取最像的 top-k，再永远带上承诺/愿望和最近几条。
- **轻量优先**：默认调中转的 `embeddings` 接口算向量（`EMBED_BACKEND=gateway`），不下大模型、不占内存，最适合小服务器。
- **永不崩**：拿不到向量就自动降级成关键词检索，聊天照常。
- 记忆条数 ≤ `FULL_MEMORY_LIMIT`(默认 60) 时仍全量带上，超过才启用精挑。

**怎么开（在服务器上）**：
```bash
cd /root/-1/platform
nano .env            # 填 EMBED_MODEL=（向中转客服确认它支持的嵌入模型名）
git pull && ./venv/bin/python vector_search.py backfill   # 给已有记忆补向量
sudo systemctl restart gude
```
看状态 / 手动回填（也可在网页调）：
```bash
curl -s localhost:8000/api/vector/status      # backend/model/available/indexed
./venv/bin/python vector_search.py search "我的车叫什么"   # 试搜
```
> 若中转不支持 embeddings，把 `EMBED_BACKEND=local` 可改用服务器本地中文模型
> （`BAAI/bge-small-zh-v1.5`，需 `pip install sentence-transformers`，较重，4G 内存慎用）。

## 🔒 隐私

- API 密钥、记忆库、聊天记录全在**你自己的服务器**上。
- `.env` 和 `memories.db` 不会进 git（见 .gitignore）。
- 可在 `.env` 设 `ACCESS_PASSCODE` 加一道访问口令。
