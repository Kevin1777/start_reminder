# 赛事提醒 VPS 一键启动

适用 Ubuntu 22.04+ / Debian 12+，需要管理员权限和正常外网连接。安装后每分钟检查一次、每小时刷新赛程，通过企业微信机器人发送提醒，开机自动运行。

## 首次启动

1. 将 `football-reminder-vps.zip` 上传到 VPS 并解压，进入解压目录。
2. 先关闭本机运行赛事提醒的窗口，避免本机和 VPS 同时推送。
3. 如需保留本机的已提醒记录，在启动前将本机 `E:\Football\data\sent.json` 单独上传为解压目录中的 `data/sent.json`。安装包不含此个人状态文件；VPS 已有状态时不会覆盖。
4. 执行：

   ```bash
   sudo bash start_reminder_vps.sh
   ```

5. 首次按提示粘贴机器人 Webhook。输入时不显示字符，按回车确认。Webhook 是发送消息的凭证，请勿公开分享。

再次执行同一命令可安装、更新并启动；已有 VPS 配置与状态会保留。更新时使用新安装包解压目录中的脚本。

## 常用操作

在解压目录执行：

```bash
sudo bash start_reminder_vps.sh status   # 查看运行状态
sudo bash start_reminder_vps.sh logs     # 查看日志
sudo bash start_reminder_vps.sh stop     # 停止提醒
sudo bash start_reminder_vps.sh help     # 查看帮助
```

停止后，重新执行无参数命令即可启动。

## 文件位置与确认

- 程序：`/opt/five-league-reminder`
- 配置：`/etc/five-league-reminder.env`
- 已提醒记录：`/var/lib/five-league-reminder/sent.json`
- 赛程缓存：`/var/lib/five-league-reminder/schedule_cache.json`

时间按 `Asia/Shanghai` 判断。若需修改 Webhook 或提醒时间，编辑上述 VPS 配置文件。

启动后检查状态和日志，确认赛程成功获取、定时检查持续运行，并在实际提醒时间确认机器人消息送达。VPS 必须能访问雷速赛程页面、其公开数据服务器及企业微信接口；本地测试通过不等于 VPS 已完成实际部署验收。

安装包为通用包，不包含个人 Webhook、账号凭证、本机配置或已提醒记录。
