# eew-cli-monitor / 地震预警命令行监控程序

基于 **Wolfx**、**P2PQuake**、**NIED**、**FAN** 数据源的地震预警命令行工具。通过 WebSocket 实时接收地震速报，在终端中以彩色表格展示详细预警信息，并支持声音报警、推送通知、P/S波到达倒计时等功能。

![地震预警效果图](./image/image1.png)

## 数据源

| 数据源 | 类型 | 子源 |
|--------|------|------|
| **Wolfx** | WebSocket | JMA (日本气象厅), CENC (中国地震台网), SC (四川地震局), FJ (福建地震局), CQ (重庆地震局), cenc_eqlist (中国地震目录), jma_eqlist (日本地震目录) |
| **P2PQuake** | EPSP (`p2p`) + JSON API v2 WebSocket (`p2pjson`) | JMA (日本气象厅), 海啸预报, 地震感知情报 |
| **NIED** | WebSocket | 日本防灾科学技术研究所 |
| **FAN Studio** | WebSocket | cea, cwa-eew, jma, cenc, cwa, usgs, sa, emsc, bcsf, gfz, usp, kma, kma-eew, fssn, fssn-cmt, cea-pr, ningxia, guangxi, shanxi, beijing, yunnan, hko；另有 weatheralarm (气象预警) 与 tsunami (海啸) 两种特殊消息 |

## 功能特点

- **实时监控** — 通过 WebSocket 持续接收数据，新地震瞬时报出
- **彩色表格** — 使用 `rich` 库在终端中渲染格式化的地震信息表
- **事件去重** — 基于事件ID自动去重，每条地震只提醒一次
- **用户位置** — 配置个人位置，自动计算震中距、本地预估烈度
- **P/S波倒计时** — 动态显示 P 波和 S 波到达倒计时
- **无震感地震通报** — 烈度为 0 的无感地震可按震级阈值单独通报 (Windows/Bark)
- **ASCII 地图** — 在终端中显示中国/世界 ASCII 地图并标注震中
- **地震目录** — 实时接收中国/日本地震目录 (cenc_eqlist/jma_eqlist)，并支持 `list` 命令查询
- **交互式配置向导** — 运行 `setup` 逐步配置，支持通过 IP 自动定位
- **多级预警** — 按预估烈度分三级 (tier1/tier2/tier3)，每级可独立配置
- **声音警报** — 5种 WAV 音效，随预警级别自动切换
- **Windows 通知** — 原生 Toast 弹窗提醒
- **Bark 推送** — 支持 iOS Bark App 推送通知
- **CSV 导出** — 可将地震数据导出为 CSV 文件
- **交互命令** — 运行时动态启用/禁用数据源、子源、切换调试模式等
- **模拟测试** — 内置模拟地震测试 (M1/M4/M6/M8 及 M5.1 印尼巴布亚)
- **配置持久化** — 所有设置自动保存到 `config.json`
- **断线重连** — 各数据源独立自动重连

## 从 Release 下载

前往 [Releases 页面](https://github.com/WangLi0101/eew-cli-monitor/releases) 下载最新版本 `eew-cli-monitor.exe`，下载后双击即可运行（已打包所有依赖和音效文件）。

## 环境要求

- Python 3.7+
- 网络连接

## 安装

### 手动安装

1. 克隆或下载本仓库
2. 安装依赖：
   ```cmd
   pip install -r requirements.txt
   ```
   依赖列表：`requests>=2.25.0`、`rich>=10.0.0`、`websocket-client>=1.6.0`

3. 运行：
   ```cmd
   python eew-cli-monitor.py
   ```

### 打包为独立 exe

```cmd
pyinstaller --onefile --console --add-data "sounds;sounds" --exclude-module gevent eew-cli-monitor.py
```

> 注：`sounds` 目录包含全部 5 种音效（alert/countdown/EEW0/EEW1/EEW2.wav），打包时需一并包含。

## 配置说明

编辑 `config.json` 进行配置：

| 配置路径 | 字段 | 含义 | 默认值 | 示例 |
|----------|------|------|--------|------|
| `location.name` | 字符串 | 用户位置名称（仅用于显示） | `null` | `"成都理工"` |
| `location.latitude` | 浮点数 | 用户纬度，用于距离/本地烈度计算（可前往 [腾讯位置服务](https://lbs.qq.com/getPoint/) 拾取坐标） | `null` | `30.67` |
| `location.longitude` | 浮点数 | 用户经度 | `null` | `104.14` |
| `sources.<key>.enabled` | 布尔 | 数据源是否启用 | wolfx: true, fan: true, 其余 false | `true` |
| `sources.<key>.url` | 字符串 | WebSocket 连接地址 | 各源默认 URL | `"wss://ws-api.wolfx.jp/all_eew"` |
| `sources.<key>.fallback_urls` | 字符串数组 | 备用连接地址 | `[]` | `["wss://ws.fanstudio.hk/all"]` |
| `filters.<source>.<subtype>` | 布尔 | 子源开关 | wolfx: jma/jma_eqlist=false, cenc/sc/fj/cq/cenc_eqlist=true; fan: cea/cwa-eew/cenc/cwa/cea-pr/ningxia/guangxi/shanxi/beijing/yunnan/hko/fssn/fssn-cmt=true, 其余 false | `true` |
| `alert.bark_url` | 字符串/null | Bark 推送 URL（在 App Store 安装 Bark App 后获取），留 null 则不推送 | `null` | `"https://api.day.app/YourKey/"` |
| `alert.no_sensation_report` | 布尔 | 烈度为 0 的无感地震是否通过 Windows/Bark 通报 | `false` | `true` |
| `alert.no_sensation_mag_threshold` | 浮点数 | 无感地震最小震级（仅通报 ≥ 该震级的无感地震） | `4.5` | `4.5` |
| `alert.tiers.tier1` | 对象 | `{min:1.0, max:2.0}` 烈度 1~2 级，windows/bark 均开 | 同上 | `{"min":1.0,"max":2.0}` |
| `alert.tiers.tier2` | 对象 | `{min:2.0, max:3.0}` 烈度 2~3 级，windows/bark 均开 | 同上 | `{"min":2.0,"max":3.0}` |
| `alert.tiers.tier3` | 对象 | `{min:3.0, max:12.0}` 烈度 ≥3 级，windows/bark 均开 | 同上 | `{"min":3.0}` |
| `export_path` | 字符串/null | CSV 导出文件路径，null 则自动生成 | `null` | `"quakes.csv"` |
| `debug` | 布尔 | 调试日志开关 | `false` | `true` |

## 交互命令

程序运行中可直接输入命令：

| 命令 | 说明 |
|------|------|
| `help` | 显示帮助 |
| `test0` ~ `test3` | 模拟 M1/M4/M6/M8 级地震（汶川） |
| `test5` | 模拟 M5.1 级地震（印尼巴布亚） |
| `debug [on/off]` | 开启/关闭调试模式 |
| `export on/off` | 开启/关闭 CSV 导出 |
| `export path <路径>` | 设置导出文件路径 |
| `list [n]` | 获取已启用的地震目录源（cenc_eqlist/jma_eqlist），n 为条数（默认 3） |
| `map [world]` | 显示 ASCII 地图（默认中国，`map world` 显示世界） |
| `stop <source>` | 停用数据源 (wolfx/p2p/p2pjson/nied/fan/all) |
| `stop <source>/<subtype>` | 停用子源 (如 `stop fan/cenc`) |
| `stop <source>/all` | 停用该数据源所有子源 |
| `enable <source>` | 启用数据源 |
| `enable <source>/<subtype>` | 启用子源 |
| `enable <source>/all` | 启用该数据源所有子源 |
| `restart <source>` | 重启数据源（或 `restart all`） |
| `setup` | 运行交互式配置向导 |
| `status` | 查看所有数据源及子源状态 |

退出：`Ctrl + C`

## 致谢

- 地震预警数据由 [Wolfx Project](https://wolfx.jp/)、[P2PQuake](https://www.p2pquake.net/)、[NIED](https://www.bosai.go.jp/sp/)、[FAN](https://api.fanstudio.tech/) 提供
- [DeepSeek](https://deepseek.com/) 协助代码编写

## 许可证

MIT License

==================
## 上游项目README
==================
# eew-cli-monitor
# 地震预警命令行监控程序

基于 Wolfx , P2PQuake API , NIED , FAN的地震预警命令行工具。程序会每秒轮询一次地震速报数据，当检测到新地震时，会在终端中以彩色表格形式显示详细预警信息（震中、震级、深度、坐标、最大震度/烈度、精度信息等）。

## 支持数据源：

1.wolfx 
- 日本气象厅 (JMA)
- 中国地震台网中心 (CENC)
- 四川地震局 (SC)
- 福建地震局 (FJ)
- 重庆地震局 (CQ)

2.P2PQuake
- 日本气象厅 (JMA)
   
3.NIED
- 日本防灾科学技术研究所(NIED)

4.FAN
- 日本气象厅 (JMA)
- 自然资源部海啸预警中心 (tsunami)
- 中国地震台网地震信息 (cenc)
- 中国地震预警网 (cea)
- 中国地震预警网省级网地震预警 (cea-pr)
- 宁夏自治区地震局地震信息 (ningxia)
- 广西壮族自治区地震局地震信息 (guangxi)
- 山西省地震局地震信息 (shanxi)
- 北京市地震局地震信息 (beijing)
- 云南省地震局地震信息 (yunnan)
- 台湾省气象署地震报告 (cwa)
- 台湾省气象署地震预警 (cwa-eew)
- 香港天文台地震信息 (hko)
- 日本气象厅地震预警 (jma)
- 美国 ShakeAlert 地震预警 (sa)
- 欧洲地中海地震中心地震信息 (emsc)
- 法国中央地震研究所地震信息 (bcsf)
- 德国地学研究中心地震信息 (gfz)
- 巴西圣保罗大学地震信息 (usp)
- 韩国气象厅地震信息 (kma)
- 韩国气象厅地震预警 (kma-eew)
- 韩国气象厅 PEWS 测站实时数据 (kma-station)
- FSSN 地震信息 (fssn)
- FSSN 矩心矩张量解(CMT) (fssn-cmt)

5.FANW
- 中国气象局气象预警(weatheralarm)

![地震预警效果图](./image/image1.png)

## 功能特点

- 每秒检查一次，无新地震时**完全静默**，不影响终端其他操作。
- 新地震触发时**立即弹出彩色表格**。
- 每个地震只提醒一次（基于事件ID去重）。
- 支持显示坐标、最大震度（日本）或最大烈度（中国）、震源深度、精度信息、警报区域示例等。
- 可灵活启用/禁用任意数据源。
- 可打包成独立 `.exe` 文件，双击即可运行。

## 环境要求

- Python 3.7 或更高版本
- 网络连接（用于访问 Wolfx API）

## 安装步骤
 
### 自动安装

下载最新发行版

### 手动安装
1. 获取程序代码

- 访问本仓库页面
- 点击绿色的 **Code** 按钮 → **Download ZIP**
- 解压到任意文件夹（例如 `C:\eew-cli-monitor`）
   
2. 获取第三方库
- 在py文件目录下
- requests>=2.25.0
- rich>=10.0.0
- websocket-client>=1.6.0
```cmd
pip install requests rich websocket-client
```
或
```cmd
pip install -r requirements.txt
```

3. 运行程序
```cmd
python eew-cli-monitor.py
```
4. 退出程序
   
**在命令提示符窗口中按 Ctrl + C 组合键，或直接关闭窗口。**

### 可选：打包成独立可执行文件
- 结构目录
```bash
eew-cli-monitor.py
sounds/
    alert.wav
    nhk_bell.wav
```
- 打包命令
```bash
pyinstaller --onefile --console --add-data "sounds/alert.wav;sounds" --add-data "sounds/nhk_bell.wav;sounds" --exclude-module gevent eew-cli-monitor.py
```
- 生成的可执行文件位于 dist/ 目录，双击即可运行。

### 使用方法
```cmd
    可用命令:
      test                          - 模拟地震多报演示
      debug                         - 开启/关闭调试模式
      export on/off                 - 开启/关闭表格导出到CSV
      export path <文件路径>         - 设置导出文件路径（相对路径）
      stop <source>                 - 停用数据源 (wolfx/p2p/nied/fan/fanw/all)
      stop <source>/<subtype>       - 停用子源 (如 stop fan/cenc)
      stop <source>/all             - 停用该数据源所有子源 (如 stop fan/all)
      enable <source>               - 启用数据源
      enable <source>/<subtype>     - 启用子源
      enable <source>/all           - 启用该数据源所有子源 (如 enable fan/all)
      restart <source>              - 重启数据源 (或 restart all)
      reset                         - 一键恢复所有配置到默认状态并自动重连
      status                        - 查看所有数据源状态
      help                          - 显示此帮助
    快捷键: Ctrl+C 退出
```

### 说明

- 本人为高中生，能力有限，项目如有错误请谅解，可以向3822104508@qq.com提交错误,本人会尽力解决
   
### 致谢

- 本程序使用的所有地震预警数据均由 [Wolfx Project](https://wolfx.jp/) , [P2PQuake](https://www.p2pquake.net/) , [NIED](https://www.bosai.go.jp/sp/) , [FAN](https://api.fanstudio.tech/) 提供，感谢他们的无私贡献。
- 感谢 [DeepSeek](https://deepseek.com/) 人工智能助手协助编写、优化和调试本程序代码。
   
### 许可证
- 本项目采用 MIT 许可证。
