# jav-scraper

AV 元数据刮削命令行工具，输入番号自动获取元数据、封面、演员头像，生成 Emby / Plex 兼容的文件结构。

## 特性

- **番号智能识别** — 自动修正大小写和格式（`jul999` → `JUL-999`）
- **反爬虫** — 使用 [curl_cffi](https://github.com/yifeikong/curl_cffi) 浏览器指纹模拟，绕过 Cloudflare 等防护
- **多数据源**
  - [JavDB](https://javdb.com) — 元数据（标题、演员、类别、片商、评分等）
  - [DMM](https://dmm.co.jp) CDN — 高清封面图
  - [Gfriends](https://github.com/gfriends/gfriends) — 3万+ 演员头像数据库
- **Emby / Plex 兼容** — 生成标准 NFO + 图片文件结构

## 安装

```bash
# Python 3.8+
pip install curl_cffi
```

## 使用

```bash
# 基本用法
python jav.py -n JUL-999

# 自动修正格式
python jav.py -n jul999       # -> JUL-999
python jav.py -n sone290      # -> SONE-290

# 多个番号
python jav.py -n SONE-290 DASS-341 IPX-337

# 自定义输出目录
python jav.py -n JUL-999 -o /path/to/output

# 同时生成 Plex 兼容文件
python jav.py -n JUL-999 --plex
```

## 输出结构

默认输出到 `~/javoutput/{番号}/`：

```
JUL-999/
├── movie.nfo           # 元数据 (Emby/Kodi/Plex)
├── poster.jpg          # 封面
├── fanart.jpg          # 背景图
└── .actors/
    └── 大島優香.jpg     # 演员头像
```

加 `--plex` 额外生成：

```
JUL-999/
├── movie.nfo           # Emby/Kodi
├── JUL-999.nfo         # Plex (XBMCnfoImporter)
├── poster.jpg
├── fanart.jpg
├── art.jpg             # Plex 背景图
├── JUL-999-poster.jpg  # Plex 按文件名匹配
└── .actors/
    └── 大島優香.jpg
```

## 番号格式支持

| 输入 | 识别为 |
|------|--------|
| `jul999` | `JUL-999` |
| `JUL-999` | `JUL-999` |
| `sone290` | `SONE-290` |
| `FC2-PPV-1234567` | `FC2-PPV-1234567` |
| `fc2ppv1234567` | `FC2-PPV-1234567` |
| `259LUXU-1234` | `259LUXU-1234` |
| `123456-789` | `123456-789` |

## NFO 包含字段

标题、原始标题、番号、DMM CID、发行日期、年份、时长、片商、导演、系列、类别、评分、演员、分级

## 注意事项

- 刮削间隔默认 2 秒，避免被限流
- 遇到 403 会自动等待 10 秒重试
- 演员头像缓存在 `~/.cache/jav_gfriends.json`（24小时有效）
- `.actors/` 是隐藏目录，macOS Finder 按 `Cmd+Shift+.` 显示

## License

MIT
