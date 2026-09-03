# 每日热点早报（国内新闻 + AI 圈 → 微信测试号）

每天早上 8:00 自动聚合国内热点（要闻/微博/知乎/百度/微信热文）和 AI 圈热点（量子位/AIbase/36氪/HF 论文/GitHub Trending），生成日报网页并推送到你的微信（公众号测试号卡片消息，点开可看全文）。

```
触发（二选一，自动去重）
 ├─ Windows 任务计划  每天 08:00 本机运行（主）
 └─ GitHub Actions    每天 08:10 云端运行（备用，电脑关机也发）
        ↓
 抓取 13 个数据源（每个源有 2~4 条兜底通道，单源失败不影响整体）
        ↓
 生成日报 HTML → git push → GitHub Pages 上线（历史可回看）
        ↓
 微信测试号模板消息 → 点击卡片打开当日完整日报
```

## 目录结构

```
push_daily.py        主入口：--dry-run 只抓不推 / --force 跳过查重 / --no-git 跳过发布
config.yaml          数据源开关、条数、推送参数（改完即生效）
src/fetchers.py      数据源适配器（直连 → codelife → 60s/DailyHotApi 逐级兜底）
src/render.py        微信卡片摘要 + 日报 HTML 渲染
src/push_wechat.py   测试号 access_token + 模板消息
src/dedupe.py        当日去重（查 GitHub 上 docs/日期.html 是否已存在）
docs/                GitHub Pages 根目录（每日一页 + index 归档）
.github/workflows/   云端备用定时任务
run.bat              任务计划程序入口（日志写 logs/run.log）
.env                 微信与 GitHub 凭据（不提交）
```

## 首次配置（共 3 块，约 20 分钟）

### 第 1 块：微信测试号（5 分钟）

1. 浏览器打开 https://mp.weixin.qq.com/debug/cgi-bin/sandbox?t=sandbox/login ，微信扫码登录。
2. 页面顶部复制 `appID` 和 `appsecret`。
3. 页面中部"测试号二维码"用**你自己的微信**扫码关注；随后在页面下方"用户列表"里复制你的 `openid`（一串 `o` 开头的字符）。
4. "模板消息接口"→"新增测试模板"：
   - 模板标题：`每日热点早报`
   - 模板内容：
     ```
     {{date.DATA}}
     {{digest.DATA}}
     点击本条消息查看完整日报
     ```
   - 保存后复制**模板 ID**。

### 第 2 块：GitHub 仓库 + Pages（10 分钟）

1. 在 GitHub 新建一个**公开**仓库（例如 `news-daily`），**不要**勾选初始化 README。
2. 本地推送代码（在 `wechat-news-daily` 目录）：
   ```bash
   git init
   git add .
   git commit -m "init: 每日热点早报"
   git branch -M main
   git remote add origin https://github.com/<你的用户名>/news-daily.git
   git push -u origin main
   ```
3. 仓库 Settings → Pages → Build and deployment → Source 选 **Deploy from a branch**，Branch 选 **main**、Folder 选 **/docs** → Save。（日报文件都在 `docs/` 目录，这正是 GitHub 原生支持的选项；稍等 1 分钟 Pages 上线后，`https://<用户名>.github.io/news-daily/` 就是日报归档页）
4. 仓库 Settings → Secrets and variables → Actions → New repository secret，逐个添加：
   | Name | 值 |
   |---|---|
   | `WX_APPID` | 测试号 appID |
   | `WX_SECRET` | 测试号 appsecret |
   | `WX_OPENID` | 你的 openid |
   | `WX_TEMPLATE_ID` | 模板 ID |
   | `GH_REPO` | `你的用户名/news-daily` |
   | `PAGES_URL` | `https://你的用户名.github.io/news-daily` |
5. Actions 页 → 选 `daily-push` → Run workflow 手动触发一次，验证云端链路（Actions 用的 GITHUB_TOKEN 无需配置，自动注入）。

### 第 3 块：本地 .env + 任务计划（5 分钟）

1. 复制 `.env.example` 为 `.env`，填入与上面相同的 6 项（GH_REPO、PAGES_URL 也要填，本地去重和 git 推送要用）。
2. Windows 任务计划已由安装脚本注册（见下文），也可手动注册：
   ```bash
   schtasks /Create /TN "WeChatNewsDaily" /TR "\"C:\Users\23324\Desktop\个性化推荐系统\wechat-news-daily\run.bat\"" /SC DAILY /ST 08:00 /F
   ```

## 常用命令

```bash
python push_daily.py --dry-run    # 只抓取渲染，docs/ 本地预览，不发布不推送
python push_daily.py              # 完整流程（有当日去重）
python push_daily.py --force      # 忽略去重强制再推一条
```

## 日常调整（config.yaml）

- **加减版块**：改 `sources.*.enabled`（抖音、B站、机器之心默认关）。
- **条数**：`sources.*.top_n`（网页条数）；卡片摘要里每版块条数在 `digest.items_per_section`。
- **推送时间**：任务计划里改 08:00；Actions 改 `.github/workflows/daily-push.yml` 的 cron（注意是 UTC，北京时间 = UTC+8）。
- 摘要总长上限 `digest.max_chars: 480`，超出部分自动截断（全文始终在网页里）。

## 故障排查

| 现象 | 处理 |
|---|---|
| 微信收不到 | 跑 `python push_daily.py --force` 看终端报错；`errcode 40001`=appsecret 错；`43004`=openid 错（须是关注了测试号的那个）；`40037`=模板 ID 错 |
| 卡片点击打不开 | Pages 没开好，或 PAGES_URL 填错。浏览器直接访问 `PAGES_URL/当天日期.html` 验证 |
| 某版块显示"暂不可用" | 该源所有兜底通道都挂了，不影响其他版块；长期挂可换源或关闭 |
| 收到两条 | 两个触发端同时跑的竞态（正常不会，间隔 10 分钟）；多发无害，可忽略 |
| 电脑关机没收到 | 本机 08:00 没跑，等 08:10 Actions 兜底；检查 Actions 运行记录 |
| 想看运行日志 | 本机看 `logs/run.log`；云端看仓库 Actions 页 |

## 备用通道：WxPusher（如测试号政策变化）

推送模块已抽象（`src/push_wechat.py`），如需切换到 WxPusher：官网扫码拿 SPT，把 `push_wechat.push_daily` 改为向 `https://wxpusher.zjiecode.com/api/send/message/simple-push` POST `{"content": html或文本, "spt": "SPT_xxx", "contentType": 3}` 即可，其余流程不变。
