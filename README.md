# jav-scraper

AV 元数据刮削命令行工具，输入番号自动获取元数据、封面、演员头像，生成 Emby / Plex 兼容的文件结构。

## 特性

- **番号智能识别** — 自动修正大小写和格式（`jul999` → `JUL-999`）
- **反爬虫** — 使用 [curl_cffi](https://github.com/yifeikong/curl_cffi) 浏览器指纹模拟，绕过 Cloudflare 等防护
- **多数据源**
  - [JavDB](https://javdb.com) — 元数据（标题、演员、类别、片商、评分等）
  - [DMM](https://dmm.co.jp) CDN — 高清封面图
  - [Gfriends](https://github.com/gfriends/gfriends) — 3万+ 演员头像数据库
- **Emby 原生兼容** — `movie.nfo` + `poster.jpg` + `fanart.jpg` + `.actors/`
- **Plex 兼容** — `--plex` 参数额外生成 Plex 格式文件
- **Emby API 集成** — 自动上传演员头像、触发库刷新

## 安装

```bash
# 需要 Python 3.8+
pip install curl_cffi
```

或者：

```bash
pip install -r requirements.txt
```

## 使用

```bash
# 基本用法 — 输入番号
python jav.py -n JUL-999

# 自动修正格式（大小写、横杠）
python jav.py -n jul999
python jav.py -n sone290

# 多个番号
python jav.py -n "SONE-290 DASS-341 IPX-337"
python jav.py -n SONE-290 DASS-341 IPX-337

# 自定义输出目录
python jav.py -n JUL-999 -o /path/to/output

# Plex 兼容模式（同时生成 Emby + Plex 格式）
python jav.py -n JUL-999 --plex

# 不触发 Emby 刷新
python jav.py -n JUL-999 --no-emby
```

## 输出结构

默认输出到 `~/javoutput/{番号}/`：

```
~/javoutput/
└── JUL-999/
    ├── movie.nfo              # Emby/Kodi 元数据
    ├── poster.jpg             # 封面
    ├── fanart.jpg             # 背景图
    └── .actors/
        └── 大島優香.jpg        # 演员头像
```

加 `--plex` 后额外生成：

```
└── JUL-999/
    ├── movie.nfo              # Emby
    ├── JUL-999.nfo            # Plex (XBMCnfoImporter)
    ├── poster.jpg             # 通用
    ├── fanart.jpg             # Emby
    ├── art.jpg                # Plex 背景图
    ├── JUL-999-poster.jpg     # Plex 按文件名匹配
    └── .actors/
        └── 大島優香.jpg
```

## 使用流程

1. 下载影片文件
2. 运行 `python jav.py -n 番号` 刮削元数据
3. 将影片文件移入 `~/javoutput/{番号}/` 文件夹
4. 将整个文件夹移到媒体库目录（如 `/Volumes/AV/`）
5. Emby/Plex 自动识别

## 配置

编辑 `jav.py` 顶部的配置项：

```python
# 输出目录
DEFAULT_OUTPUT = os.path.expanduser("~/javoutput")

# Emby 服务器（可选，留空则不触发刷新）
EMBY_HOST = "http://192.168.88.107:8096"
EMBY_API_KEY = "your_api_key"
```

## 番号格式支持

| 输入 | 识别为 | 说明 |
|------|--------|------|
| `jul999` | `JUL-999` | 自动大写 + 加横杠 |
| `JUL-999` | `JUL-999` | 标准格式 |
| `sone290` | `SONE-290` | 自动修正 |
| `FC2-PPV-1234567` | `FC2-PPV-1234567` | FC2 |
| `fc2ppv1234567` | `FC2-PPV-1234567` | FC2 自动修正 |
| `259LUXU-1234` | `259LUXU-1234` | 数字前缀番号 |
| `123456-789` | `123456-789` | 无码格式 |

## NFO 元数据字段

生成的 `movie.nfo` 包含以下信息：

- 标题（title）、原始标题（originaltitle）
- 番号（num）、DMM CID
- 发行日期（premiered）、年份（year）
- 时长（runtime）
- 片商（studio）、导演（director）
- 系列（set）
- 类别/标签（genre）
- 评分（rating）
- 演员（actor）— 不写远程 thumb URL，避免 Emby 显示碎图
- 分级（mpaa: NC-17）

## 注意事项

- 刮削间隔默认 2 秒，避免被 JavDB 限流
- 如遇 403 错误，脚本会自动等待 10 秒重试
- Gfriends 头像数据库会缓存到 `~/.cache/jav_gfriends.json`（24小时有效）
- 演员头像为隐藏目录 `.actors/`，macOS Finder 按 `Cmd+Shift+.` 显示

## License

MIT
