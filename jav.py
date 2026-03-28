#!/usr/bin/env python3
"""
jav - AV 元数据刮削工具
用法:
  python jav.py -n JUL-999          # 刮削单个番号
  python jav.py -n jul999            # 自动修正格式 -> JUL-999
  python jav.py -n "SONE-290 SSIS-706"  # 多个番号(空格分隔)
  python jav.py -n SONE-290 -o /tmp/out # 自定义输出目录

输出到 ~/javoutput/{番号}/ :
  movie.nfo, poster.jpg, fanart.jpg, .actors/{name}.jpg
"""

import os
import re
import sys
import json
import time
import shutil
import argparse
import logging
import xml.etree.ElementTree as ET
from urllib.parse import quote

logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger('jav')

# ─── 默认配置 ───
DEFAULT_OUTPUT = os.path.expanduser("~/javoutput")
SCRAPE_DELAY = 2

# ─── curl_cffi session (反爬虫) ───
_session = None
_proxy = None

def set_proxy(proxy_url):
    global _proxy
    _proxy = proxy_url

def _detect_proxy():
    """检测系统代理设置"""
    for env in ('https_proxy', 'HTTPS_PROXY', 'http_proxy', 'HTTP_PROXY', 'ALL_PROXY', 'all_proxy'):
        val = os.environ.get(env)
        if val:
            return val
    # macOS: 尝试读取网络偏好的 web proxy
    try:
        import subprocess
        r = subprocess.run(['networksetup', '-getwebproxy', 'Wi-Fi'],
                          capture_output=True, text=True, timeout=3)
        for line in r.stdout.splitlines():
            if line.startswith('Enabled:') and 'Yes' in line:
                server = port = None
                for l2 in r.stdout.splitlines():
                    if l2.startswith('Server:'): server = l2.split(':', 1)[1].strip()
                    if l2.startswith('Port:'): port = l2.split(':', 1)[1].strip()
                if server and port:
                    return f"http://{server}:{port}"
    except Exception:
        pass
    return None

def get_session():
    global _session
    if _session is None:
        from curl_cffi import requests as cffi_requests
        proxy = _proxy or _detect_proxy()
        proxies = {"http": proxy, "https": proxy} if proxy else None
        _session = cffi_requests.Session(impersonate="chrome136", proxies=proxies)
        _session.cookies.set('over18', '1')
        _session.cookies.set('locale', 'zh')
        if proxy:
            log.info(f"  使用代理: {proxy}")
    return _session

# ─── Gfriends 演员头像缓存 ───
_gfriends = None
def get_gfriends():
    global _gfriends
    if _gfriends is not None:
        return _gfriends
    cache = os.path.expanduser("~/.cache/jav_gfriends.json")
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < 86400:
        with open(cache) as f:
            _gfriends = json.load(f)
        return _gfriends
    log.info("[Gfriends] 加载演员头像数据库...")
    s = get_session()
    resp = s.get("https://raw.githubusercontent.com/gfriends/gfriends/master/Filetree.json", timeout=30)
    if resp.status_code != 200:
        _gfriends = {}
        return _gfriends
    data = json.loads(resp.text)
    idx = {}
    for folder, files in data.get('Content', {}).items():
        if isinstance(files, dict):
            for fname in files:
                name = fname.rsplit('.', 1)[0] if '.' in fname else fname
                idx[name] = f"{folder}/{fname}"
    try:
        with open(cache, 'w') as f:
            json.dump(idx, f)
    except:
        pass
    _gfriends = idx
    log.info(f"[Gfriends] {len(idx)} 个演员")
    return idx


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  番号解析
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def normalize_number(raw):
    """
    将用户输入的番号标准化:
      jul999   -> JUL-999
      JUL-999  -> JUL-999
      sone290  -> SONE-290
      FC2-PPV-1234567 -> FC2-PPV-1234567
      259LUXU-1234 -> 259LUXU-1234
      123456-789 -> 123456-789 (无码)
    """
    s = raw.strip()
    if not s:
        return None

    fc2 = re.match(r'(?i)(fc2-?ppv)-?(\d+)', s)
    if fc2:
        return f"FC2-PPV-{fc2.group(2)}"

    unc = re.match(r'^(\d{6})[-_](\d{2,3})$', s)
    if unc:
        return f"{unc.group(1)}-{unc.group(2)}"

    th = re.match(r'(?i)^(n)(\d{4})$', s)
    if th:
        return f"n{th.group(2)}"

    npre = re.match(r'(?i)^(\d+[a-z]+)-?(\d{3,5})$', s)
    if npre:
        return f"{npre.group(1).upper()}-{npre.group(2)}"

    std = re.match(r'(?i)^([a-z]{2,10})-?(\d{3,5})$', s)
    if std:
        return f"{std.group(1).upper()}-{std.group(2)}"

    return s.upper()


def number_to_cid(number):
    """番号 -> DMM CID (例: SONE-290 -> sone00290)"""
    m = re.match(r'^([A-Z]+)-(\d+)$', number)
    if not m:
        return None
    prefix = m.group(1).lower()
    num = m.group(2).zfill(5)
    return f"{prefix}{num}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  JavDB 刮削 (curl_cffi 反爬)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def scrape_javdb(number):
    """刮削 JavDB 获取完整元数据"""
    s = get_session()

    url = f"https://javdb.com/search?q={quote(number)}&f=all"
    resp = s.get(url, timeout=15)
    if resp.status_code == 403:
        log.warning("  [JavDB] 被限流(403)，等待10秒重试...")
        time.sleep(10)
        resp = s.get(url, timeout=15)
    if resp.status_code != 200:
        log.error(f"  [JavDB] 搜索失败 HTTP {resp.status_code}")
        return None

    # 精确匹配 video-title 区域
    items = re.findall(
        r'<a[^>]*href="(/v/[^"]+)"[^>]*>.*?<div class="video-title">\s*<strong>\s*([^<]+?)\s*</strong>',
        resp.text, re.DOTALL
    )
    if not items:
        items = re.findall(
            r'<a[^>]*href="(/v/[^"]+)"[^>]*>.*?<strong>([^<]+)</strong>',
            resp.text, re.DOTALL
        )

    detail_path = None
    num_upper = number.upper()
    num_nodash = num_upper.replace('-', '')
    for path, vid in items:
        v = vid.strip().upper()
        if v == num_upper or v.replace('-', '') == num_nodash:
            detail_path = path
            break

    if not detail_path:
        log.error(f"  [JavDB] 未找到 {number}")
        return None

    time.sleep(1)

    detail_url = f"https://javdb.com{detail_path}"
    resp = s.get(detail_url, timeout=15)
    if resp.status_code != 200:
        log.error(f"  [JavDB] 详情页失败 HTTP {resp.status_code}")
        return None

    html = resp.text
    info = {'number': number}

    # 标题
    m = re.search(r'<strong class="current-title">([^<]+)</strong>', html)
    if m:
        info['title'] = m.group(1).strip()
    else:
        m = re.search(r'<title>([^|<]+)', html)
        if m:
            t = m.group(1).strip()
            t = re.sub(r'^' + re.escape(number) + r'\s*', '', t).strip()
            info['title'] = t

    # 封面
    m = re.search(r"column-video-cover.*?<img[^>]*src=\"([^\"]+)\"", html, re.DOTALL)
    if m:
        cover = m.group(1)
        if not cover.startswith('http'):
            cover = 'https:' + cover
        info['cover'] = cover

    # 解析 panel-block
    panels = re.findall(r'<div class="panel-block[^"]*">(.*?)</div>', html, re.DOTALL)
    for panel in panels:
        clean = re.sub(r'<[^>]+>', ' ', panel)

        if re.search(r'番號', panel):
            continue

        elif re.search(r'日期', panel):
            dm = re.search(r'(\d{4}-\d{2}-\d{2})', panel)
            if dm:
                info['date'] = dm.group(1)
                info['year'] = dm.group(1)[:4]

        elif re.search(r'時長', panel):
            dm = re.search(r'(\d+)\s*分', clean)
            if dm:
                info['runtime'] = dm.group(1)

        elif re.search(r'導演', panel):
            dm = re.findall(r'<a[^>]*>([^<]+)</a>', panel)
            if dm:
                info['director'] = dm[0].strip()

        elif re.search(r'片商', panel):
            dm = re.findall(r'<a[^>]*>([^<]+)</a>', panel)
            if dm:
                info['studio'] = dm[0].strip()

        elif re.search(r'發行', panel) and 'studio' not in info:
            dm = re.findall(r'<a[^>]*>([^<]+)</a>', panel)
            if dm:
                info['studio'] = dm[0].strip()

        elif re.search(r'系列', panel):
            dm = re.findall(r'<a[^>]*>([^<]+)</a>', panel)
            if dm:
                info['series'] = dm[0].strip()

        elif re.search(r'類別', panel):
            tags = re.findall(r'<a[^>]*>([^<]+)</a>', panel)
            info['genres'] = [t.strip() for t in tags if t.strip()]

        elif re.search(r'演員', panel):
            actors = re.findall(r'<a[^>]*href="/actors/([^"]+)"[^>]*>\s*([^<]+)</a>\s*<strong class="symbol female"', panel, re.DOTALL)
            if actors:
                info['actors'] = [{'id': aid, 'name': aname.strip()} for aid, aname in actors]
            else:
                actors2 = re.findall(r'<a[^>]*href="/actors/([^"]+)"[^>]*>\s*([^<]+)</a>', panel, re.DOTALL)
                all_actors = [{'id': aid, 'name': aname.strip()} for aid, aname in actors2 if aname.strip() not in ('想看', '')]
                if all_actors:
                    info['actors'] = all_actors

        elif re.search(r'評分', panel):
            dm = re.search(r'([\d.]+)分', clean)
            if dm:
                info['rating'] = dm.group(1)

    # 简介
    m = re.search(r'class="video-meta-panel".*?劇情簡介.*?<div[^>]*>(.*?)</div>', html, re.DOTALL)
    if m:
        plot = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if plot:
            info['plot'] = plot

    return info


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  图片下载
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def download_poster(number, dest):
    """从 DMM CDN 下载封面"""
    s = get_session()
    cid = number_to_cid(number)
    if not cid:
        return False

    variants = [cid, f"118{cid}", f"1{cid}"]
    templates = [
        "https://pics.dmm.co.jp/digital/video/{c}/{c}pl.jpg",
        "https://pics.dmm.co.jp/mono/movie/adult/{c}/{c}pl.jpg",
    ]
    for c in variants:
        for tmpl in templates:
            try:
                resp = s.get(tmpl.format(c=c), timeout=12)
                if resp.status_code == 200 and len(resp.content) > 5000:
                    with open(dest, 'wb') as f:
                        f.write(resp.content)
                    return True
            except:
                continue
    return False


def download_poster_javdb(cover_url, dest):
    """从 JavDB 封面 URL 下载"""
    if not cover_url:
        return False
    s = get_session()
    try:
        resp = s.get(cover_url, timeout=15)
        if resp.status_code == 200 and len(resp.content) > 5000:
            with open(dest, 'wb') as f:
                f.write(resp.content)
            return True
    except:
        pass
    return False


def download_actor_photo(name, dest):
    """从 Gfriends 下载演员头像"""
    idx = get_gfriends()
    s = get_session()

    search_names = [name]
    clean = re.sub(r'[（(][^）)]*[）)]', '', name).strip()
    if clean != name:
        search_names.append(clean)
        for alias in re.findall(r'[（(]([^）)]+)[）)]', name):
            if alias.strip():
                search_names.append(alias.strip())

    for n in search_names:
        if n in idx:
            path = idx[n]
            url = f"https://raw.githubusercontent.com/gfriends/gfriends/master/Content/{quote(path)}"
            try:
                resp = s.get(url, timeout=20)
                if resp.status_code == 200 and len(resp.content) > 500:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, 'wb') as f:
                        f.write(resp.content)
                    return True
            except:
                pass
    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  NFO 生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def write_nfo(info, path):
    """生成 movie.nfo"""
    movie = ET.Element('movie')

    def add(tag, text):
        if text:
            el = ET.SubElement(movie, tag)
            el.text = str(text)

    number = info['number']
    title = info.get('title', '')

    full_title = f"{number} {title}" if title and number not in title else (title or number)
    add('title', full_title)
    add('originaltitle', title or number)
    add('sorttitle', number)
    add('num', number)
    add('year', info.get('year'))
    add('premiered', info.get('date'))
    add('releasedate', info.get('date'))
    add('runtime', info.get('runtime'))
    add('studio', info.get('studio'))
    add('director', info.get('director'))
    add('rating', info.get('rating'))
    add('plot', info.get('plot'))
    add('mpaa', 'NC-17')
    add('country', '日本')

    uid = ET.SubElement(movie, 'uniqueid', type='num', default='true')
    uid.text = number
    cid = number_to_cid(number)
    if cid:
        uid2 = ET.SubElement(movie, 'uniqueid', type='cid')
        uid2.text = cid

    for g in info.get('genres', []):
        add('genre', g)

    if info.get('series'):
        s = ET.SubElement(movie, 'set')
        sn = ET.SubElement(s, 'name')
        sn.text = info['series']

    for actor in info.get('actors', []):
        a = ET.SubElement(movie, 'actor')
        n = ET.SubElement(a, 'name')
        n.text = actor['name']

    tree = ET.ElementTree(movie)
    ET.indent(tree, space='  ')
    tree.write(path, encoding='utf-8', xml_declaration=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  主流程
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def process(number, output_dir, plex=False):
    """处理单个番号"""
    log.info(f"\n{'─'*50}")
    log.info(f"  {number}")
    log.info(f"{'─'*50}")

    # 如果输出目录名已经是番号，直接用，不再嵌套
    if os.path.basename(os.path.normpath(output_dir)).upper() == number.upper():
        dest = output_dir
    else:
        dest = os.path.join(output_dir, number)
    os.makedirs(dest, exist_ok=True)

    nfo_path = os.path.join(dest, 'movie.nfo')
    poster_path = os.path.join(dest, 'poster.jpg')
    if os.path.exists(nfo_path) and os.path.exists(poster_path) and os.path.getsize(poster_path) > 5000:
        log.info("  已存在，跳过 (删除目录可重新刮削)")
        return True

    # 1. 刮削元数据
    info = scrape_javdb(number)
    if not info:
        return False

    log.info(f"  标题: {info.get('title', 'N/A')}")
    log.info(f"  日期: {info.get('date', 'N/A')}  时长: {info.get('runtime', 'N/A')}分钟")
    log.info(f"  片商: {info.get('studio', 'N/A')}")
    actors = info.get('actors', [])
    if actors:
        log.info(f"  演员: {', '.join(a['name'] for a in actors)}")
    log.info(f"  类别: {', '.join(info.get('genres', []))}")

    # 2. NFO
    write_nfo(info, nfo_path)
    log.info(f"  ✓ movie.nfo")

    if plex:
        plex_nfo = os.path.join(dest, f"{number}.nfo")
        if not os.path.exists(plex_nfo):
            shutil.copy2(nfo_path, plex_nfo)
            log.info(f"  ✓ {number}.nfo (Plex)")

    # 3. 封面
    ok = download_poster(number, poster_path)
    if not ok:
        ok = download_poster_javdb(info.get('cover'), poster_path)
    if ok:
        size = os.path.getsize(poster_path)
        log.info(f"  ✓ poster.jpg ({size//1024}KB)")
    else:
        log.warning(f"  ✗ poster.jpg 下载失败")

    # 4. fanart
    fanart_path = os.path.join(dest, 'fanart.jpg')
    if os.path.exists(poster_path) and os.path.getsize(poster_path) > 5000:
        shutil.copy2(poster_path, fanart_path)
        log.info(f"  ✓ fanart.jpg")

    if plex and os.path.exists(poster_path) and os.path.getsize(poster_path) > 5000:
        for extra in [f"{number}-poster.jpg", "art.jpg"]:
            ep = os.path.join(dest, extra)
            if not os.path.exists(ep):
                shutil.copy2(poster_path, ep)
        log.info(f"  ✓ art.jpg + {number}-poster.jpg (Plex)")

    # 5. 演员头像
    for actor in actors:
        aname = actor['name']
        photo_path = os.path.join(dest, '.actors', f"{aname}.jpg")
        if download_actor_photo(aname, photo_path):
            log.info(f"  ✓ .actors/{aname}.jpg")
        else:
            log.info(f"  ✗ .actors/{aname}.jpg (未找到)")
        time.sleep(0.3)

    return True


def main():
    parser = argparse.ArgumentParser(
        description='AV 元数据刮削工具',
        usage='python jav.py -n JUL-999 [-o 输出目录]'
    )
    parser.add_argument('-n', '--number', required=True, help='番号 (支持多个，空格分隔)', nargs='+')
    parser.add_argument('-o', '--output', default=DEFAULT_OUTPUT, help=f'输出目录 (默认: {DEFAULT_OUTPUT})')
    parser.add_argument('--plex', action='store_true', help='同时生成 Plex 兼容文件')
    parser.add_argument('--proxy', help='HTTP 代理 (如 http://127.0.0.1:7890，不指定则自动检测系统代理)')

    args = parser.parse_args()
    if args.proxy:
        set_proxy(args.proxy)
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)

    numbers = []
    for raw in args.number:
        for part in raw.replace(',', ' ').split():
            n = normalize_number(part)
            if n:
                numbers.append(n)
            else:
                log.warning(f"无法识别番号: {part}")

    if not numbers:
        log.error("没有有效的番号")
        sys.exit(1)

    log.info(f"待处理: {', '.join(numbers)}")
    log.info(f"输出到: {output_dir}")

    success = 0
    fail = 0
    for num in numbers:
        try:
            if process(num, output_dir, plex=args.plex):
                success += 1
            else:
                fail += 1
        except Exception as e:
            log.error(f"  错误: {e}")
            import traceback
            traceback.print_exc()
            fail += 1
        if num != numbers[-1]:
            time.sleep(SCRAPE_DELAY)

    log.info(f"\n{'═'*50}")
    log.info(f"  完成: {success} 成功, {fail} 失败")
    log.info(f"  输出: {output_dir}")
    log.info(f"{'═'*50}")


if __name__ == '__main__':
    main()
