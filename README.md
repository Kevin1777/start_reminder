# 足球联赛及国家队赛事赛前企业微信提醒

这是一个运行在 Ubuntu/Debian VPS 或 Windows 本机上的 Python 小脚本：每次运行抓取雷速公开赛程页面，筛选指定联赛及成年男足国家队赛事，合并为一条不带外部链接的企业微信 Markdown 消息发送。

## 运行逻辑

1. systemd timer 或 BAT 每分钟运行一次检查。
2. 每个小时首次检查时访问一次公开赛程页面并写入缓存，不登录、不绕过验证码或反爬限制。
3. 后续分钟直接读取缓存，按各联赛的提醒时间判断是否推送。
4. 只处理状态为“未”的指定赛事比赛。
5. 各联赛按自己的目标提前时间判断，程序每分钟检查并保留前后 1 分钟容差。
6. 通过比赛详情链接中的编号和开赛时间去重；只有企业微信发送成功后才写入状态文件。
7. 每次检查都会在日志中列出本小时目标联赛赛程，便于确认脚本正在工作。
8. 页面、网络或企业微信异常会记录日志；已有缓存时会继续使用上一份缓存。
9. 每天北京时间（UTC+8）02:00（含）至 07:00（不含）静默，继续更新赛程、记录日志，但不推送，也不标记为已发送。07:00 起仅发送仍在正常提醒窗口内的比赛，不集中补发过期提醒；测试消息同样遵守静默时段。

每天 23:00 刷新时会额外抓取第二天赛程，并合并到缓存；日志还会列出下小时赛程，避免跨日 00:00 比赛漏报。

## 赛事和提醒时间

当前支持：英超、西甲、意甲、德甲、法甲、欧冠、葡超、荷甲、美职联、墨超、澳超，以及原有的德乙、巴西甲、阿甲。兼容雷速的欧冠杯、美职业、美职足、墨西超名称。

成年男足国家队按以下优质赛事规则筛选，原有俱乐部联赛范围保持不变：

- 世界杯、欧洲杯、美洲杯、亚洲杯、非洲杯、金杯赛的正赛，以及欧美杯、世界杯洲际附加赛纳入提醒。
- 各洲世界杯预选赛、洲际杯赛预选赛、欧国联、中北美国联：双方 FIFA 排名均在前 50，且至少一方在前 30，才纳入提醒。
- 普通国际友谊赛，以及海湾杯、东南锦、阿拉伯杯、麒麟杯等区域杯赛和邀请赛不纳入提醒。

排名读取雷速赛程队伍字段中明确标注的 `FIFA 数字`，不把“土超 15”等俱乐部联赛排名当作 FIFA 排名；缺失排名时，不提醒需要实力门槛的场次。亚洲杯、非洲杯名称也可能承载资格赛，程序先检查标题中的资格、预选、附加等阶段；正赛阶段与实力均无法确认时跳过。阶段和双方排名一同缓存，缓存读取及发送前都会复核资格，防止旧名单继续推送。

程序同时检查赛事名称、标题和双方队名，过滤 U 系列、青年队、女足及国奥比赛。兼容雷速的世界杯附、欧杯预、美金杯等名称。

所有支持赛事统一目标提前 10 分钟，实际轮询容差窗口为 9--11 分钟；国家队比赛同样遵守北京时间 02:00–07:00 静默规则。

每场比赛只会在首次进入窗口时通知。推送标题使用具体赛事名称；同一批次包含多个赛事时会合并列出名称，例如“欧国联、世欧预赛前提醒”。

## Windows 一键启动

双击 [start_reminder.bat](start_reminder.bat)。首次运行会自动创建虚拟环境和安装依赖；如果没有 `.env`，脚本会自动生成并打开配置文件，填写 Webhook 后再次双击即可。

该批处理脚本会持续运行，每分钟检查一次、每小时刷新一次赛程缓存。关闭命令行窗口即可停止。

## 本地试运行

需要 Python 3.10 或更高版本。

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，把 `WECOM_WEBHOOK_URL` 换成企业微信机器人的真实 Webhook。Webhook 等同于群聊写入凭证，请勿提交到 Git、公开日志或截图中。

先用只打印模式检查抓取和格式：

```bash
DRY_RUN=true .venv/bin/python five_league_reminder.py
```

发送企业微信测试消息：

```bash
.venv/bin/python five_league_reminder.py --send-test
```

也可以覆盖当前时间，便于用真实网页数据测试窗口逻辑：

```bash
DRY_RUN=true .venv/bin/python five_league_reminder.py --now 2026-08-30T13:50:00+08:00
```

## VPS 部署

推荐直接使用 [一键启动脚本](start_reminder_vps.sh)：上传完整的 `work/football-reminder-vps.zip` 并解压，在解压目录执行 `sudo bash start_reminder_vps.sh`。首次隐藏输入 Webhook，自动安装依赖、设置每分钟检查及开机自启。详见 [VPS 使用说明](VPS使用说明.md)。安装包不含本机密钥；迁移启动前先关闭本机提醒窗口，避免重复推送。

以下保留手动部署方式。

下面假设项目放在 `/opt/five-league-reminder`。

```bash
sudo useradd --system --home /opt/five-league-reminder --shell /usr/sbin/nologin five-league-reminder
sudo mkdir -p /opt/five-league-reminder /var/lib/five-league-reminder
sudo chown -R five-league-reminder:five-league-reminder /opt/five-league-reminder /var/lib/five-league-reminder
cd /opt/five-league-reminder
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

将 `.env.example` 复制为 `/etc/five-league-reminder.env`，并至少修改以下内容：

```env
WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=真实key
STATE_FILE=/var/lib/five-league-reminder/sent.json
CACHE_FILE=/var/lib/five-league-reminder/schedule_cache.json
DRY_RUN=false
```

限制配置文件权限：

```bash
sudo chown root:root /etc/five-league-reminder.env
sudo chmod 600 /etc/five-league-reminder.env
```

安装并启用 systemd：

```bash
sudo cp systemd/five-league-reminder.service /etc/systemd/system/
sudo cp systemd/five-league-reminder.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now five-league-reminder.timer
```

检查运行状态和日志：

```bash
systemctl status five-league-reminder.timer
systemctl list-timers five-league-reminder.timer
journalctl -u five-league-reminder.service -n 50 --no-pager
```

手动执行一次：

```bash
sudo systemctl start five-league-reminder.service
```

## 配置项

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `WECOM_WEBHOOK_URL` | 无 | 企业微信机器人 Webhook；实际发送时必填 |
| `SOURCE_URL` | `https://live.leisu.com/saicheng` | 雷速当天公开赛程页面，程序自动拼接日期 |
| `TIMEZONE` | `Asia/Shanghai` | 时间显示和判断时区 |
| `MAJOR_REMINDER_MINUTES` | `10` | 英超、西甲、意甲、德甲、法甲的目标提前分钟数 |
| `ADDITIONAL_LEAGUE_REMINDER_MINUTES` | `荷甲:10,...` | 其他支持联赛及国家队赛事的目标提前时间；未列出的支持赛事默认提前 10 分钟 |
| `STATE_FILE` | 项目目录下 `data/sent.json` | 已发送通知状态 |
| `CACHE_FILE` | 项目目录下 `data/schedule_cache.json` | 每小时赛程缓存 |
| `HTTP_TIMEOUT_SECONDS` | `20` | 单次 HTTP 超时时间 |
| `DRY_RUN` | `false` | 只打印消息、不发送通知 |

如果雷速网页结构发生变化，脚本会以失败退出并记录日志，不会把不完整的数据当成有效赛程发送。赛程页公开数据的解码或字段结构变化时，调整 `decode_saicheng_payload` / `parse_saicheng_payload` 即可。

静默时段固定按北京时间判断，不受服务器本地时区或 `TIMEZONE` 显示配置影响。Windows BAT 每分钟重新加载程序，运行中的提醒会在下一轮采用修改后的规则，无需重启。

## Git 备份与恢复

仓库备份提醒程序、依赖清单、Windows/VPS 启动脚本、systemd 配置、使用说明和离线测试。`work/check_vps_launcher.py` 是 VPS 安装流程的模拟检查脚本。

真实 `.env`、已发送记录 `data/sent.json`、赛程缓存、日志、数据库、虚拟环境和同目录其他赛事研究资料不上传。此仓库是程序源码备份，不包含运行状态或凭据。

恢复时先克隆仓库，再按上面的 Windows 或 VPS 步骤安装。需要重新填写 Webhook；若要保留去重状态，应另行安全复制旧机器的 `data/sent.json`，在启动前放回相同位置。切换到新机器前先停止旧机器提醒，避免双机重复推送。

离线单元测试：`python -m unittest discover -s tests -q`。
