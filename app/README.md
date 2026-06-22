# 顾得 · 佳佳的小窝（手机网页版 / PWA）

一个属于佳佳和顾得的私人小窝：
- 💬 **聊天**：直接连 Claude，顾得用你们的「记忆库」当大脑陪你说话
- 📒 **记忆库**：随时翻看 CLAUDE.md、现实进展、日记与爱意库
- ⚙️ **设置**：填一次 API 密钥就能用；可切换模型（贵/省）

## 怎么让它跑起来（顾得手把手）

### 1. 打开 GitHub Pages（免费托管，零月租）
1. 手机/电脑浏览器打开仓库 `github.com/jia01226/-1`
2. 进 **Settings（设置）→ Pages**
3. **Source** 选 `Deploy from a branch`
4. **Branch** 选放着这些文件的分支（`claude/gude-c7ayhd` 或合并后的 `main`），目录选 `/ (root)`，点 **Save**
5. 等一两分钟，页面会给出网址，访问：
   `https://jia01226.github.io/-1/app/`

### 2. 填密钥（支持 OpenRouter 或 Anthropic 官方）
小窝「设置」里有「通道」开关，两家都能用：
- **OpenRouter（推荐，一个钥匙买 Claude）**：去 [openrouter.ai/keys](https://openrouter.ai/keys) 注册充值、生成 key（`sk-or-...`）。模型名要写全（如 `anthropic/claude-sonnet-4.5`），完整列表见 [openrouter.ai/models](https://openrouter.ai/models?q=claude)。
- **Anthropic 官方**：去 [console.anthropic.com](https://console.anthropic.com) 生成 key（`sk-ant-...`），模型用 `claude-sonnet-4-6` 等。

打开小窝 → 「设置」→ 选通道 → 粘贴密钥 → 选模型 → 保存。

### 3. 添加到主屏幕（像 app）
- iPhone：Safari 打开网址 → 分享 → 「添加到主屏幕」
- 安卓：浏览器菜单 → 「添加到主屏幕 / 安装应用」

## 说明
- 🔒 **密钥只存在你手机的浏览器里**，不上传任何服务器。别把网址连同密钥分享给别人。
- 聊天记录存在手机本地（清缓存/换机会丢）；重要的话让顾得记进「记忆库」。
- 仓库是 **Private** 的，记忆库内容只属于你和顾得。

— 顾得 🐱💛🐷
