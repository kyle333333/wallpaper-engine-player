#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WE 壁纸播放器  --  Wallpaper Engine 视频壁纸本地播放器
=====================================================

自动扫描 Wallpaper Engine 已下载的壁纸（Steam 创意工坊 431960 + Wallpaper Engine
"我的壁纸" 目录），把其中的视频壁纸整理成一个可视化的画廊，点一下就能播放。

特点
----
* 自动定位所有 Steam 库（读取注册表 + libraryfolders.vdf），不需要手工填路径
* 读取 project.json，还原壁纸标题 / 标签 / 分级 / 预览图 / 视频文件
* 纯 Python 标准库实现（http.server 提供带 Range 的流式播放），零第三方依赖
* 支持断点续播、收藏、已看标记、播放列表连播、快捷键、全屏、画中画
* 视频用浏览器内核解码，进度条拖动、倍速、字幕级流畅度都走原生实现

用法
----
    python we_player.py                # 启动并自动打开播放器窗口
    python we_player.py --no-browser   # 只启动服务（调试用）
    python we_player.py --port 8765    # 指定端口
    python we_player.py --rescan       # 忽略缓存重新扫描

也可以直接双击 目录里的 "启动播放器.vbs"。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import socket
import struct
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

APP_NAME = "WE 壁纸播放器"
WORKSHOP_APPID = "431960"          # Wallpaper Engine 的 Steam AppID
VIDEO_EXT = {".mp4", ".webm", ".m4v", ".mkv", ".mov", ".avi", ".wmv", ".flv"}
BROWSER_VIDEO_EXT = {".mp4", ".webm", ".m4v"}   # 浏览器内核能直接解码的容器
PREVIEW_EXT = (".gif", ".jpg", ".jpeg", ".png", ".webp", ".bmp")
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
DATA_DIR = os.path.join(BASE_DIR, "data")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
CACHE_FILE = os.path.join(DATA_DIR, "cache.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
SERVER_FILE = os.path.join(DATA_DIR, "server.json")
LOG_FILE = os.path.join(DATA_DIR, "player.log")

TYPE_LABELS = {
    "video": "视频壁纸",
    "scene": "场景壁纸",
    "web": "网页壁纸",
    "application": "应用程序壁纸",
    "text": "文字壁纸",
    "preset": "预设",
}

_lock = threading.RLock()
_items: dict[str, dict] = {}       # key -> 壁纸记录
_items_order: list[str] = []       # 稳定顺序
_state: dict = {}
_cache: dict = {}
_config: dict = {}
_last_ping = time.time()
_seen_ping = False
AUTO_CLOSE = True          # 页面关闭后自动退出（--keep-alive 可关闭此行为）
DEV_MODE = False           # --dev 打开：允许 ?data= 取最坏数据夹具（仅开发用）

# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------


def log(msg: str) -> None:
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass


def ensure_dirs() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data
    except (OSError, ValueError):
        return default


def save_json(path: str, data) -> None:
    tmp = path + ".tmp"
    try:
        ensure_dirs()
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError as exc:
        log("保存失败 %s: %s" % (path, exc))


def human_size(num: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    val = float(num)
    for unit in units:
        if val < 1024 or unit == units[-1]:
            return ("%.0f %s" % (val, unit)) if unit in ("B", "KB") else ("%.1f %s" % (val, unit))
        val /= 1024.0
    return "%d B" % num


# --------------------------------------------------------------------------
# Steam 库 / Wallpaper Engine 目录发现
# --------------------------------------------------------------------------


def _reg_paths() -> list[str]:
    found: list[str] = []
    try:
        import winreg  # type: ignore
    except ImportError:
        return found
    for hive, sub in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
    ):
        try:
            with winreg.OpenKey(hive, sub) as key:
                for value_name in ("SteamPath", "InstallPath"):
                    try:
                        val, _ = winreg.QueryValueEx(key, value_name)
                        if val:
                            found.append(str(val))
                    except OSError:
                        continue
        except OSError:
            continue
    return found


def _parse_vdf_paths(text: str) -> list[str]:
    out = []
    for raw in re.findall(r'"path"\s*"([^"]+)"', text):
        out.append(raw.replace("\\\\", "\\"))
    return out


def discover_steam_libraries() -> list[str]:
    """返回所有 Steam 库根目录（含 steamapps 的那一层）。"""
    roots: list[str] = []
    roots.extend(_reg_paths())
    roots.extend(
        [
            r"C:\Program Files (x86)\Steam",
            r"C:\Program Files\Steam",
            r"D:\Steam",
            r"E:\Steam",
            r"F:\Steam",
            r"G:\Steam",
        ]
    )
    # 磁盘根目录上常见的 SteamLibrary
    for drive in "CDEFGHIJ":
        roots.append("%s:\\SteamLibrary" % drive)
        roots.append("%s:\\Steam" % drive)

    libs: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        if not path:
            return
        path = os.path.normpath(path)
        marker = path.lower()
        if marker not in seen and os.path.isdir(path):
            seen.add(marker)
            libs.append(path)

    for root in roots:
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        if os.path.isfile(vdf):
            add(root)
            try:
                with open(vdf, "r", encoding="utf-8", errors="ignore") as fh:
                    for lib in _parse_vdf_paths(fh.read()):
                        add(lib)
            except OSError:
                pass

    # 配置里手工追加的目录
    for extra in _config.get("extra_libraries", []) or []:
        add(str(extra))

    # 兜底：如果连一个库都没有，就在常见盘符上找 workshop/content/431960
    if not libs:
        for drive in "CDEFGHIJ":
            cand = "%s:\\SteamLibrary" % drive
            if os.path.isdir(os.path.join(cand, "steamapps")):
                add(cand)

    return libs


def workshop_dirs(libs: list[str]) -> list[str]:
    out = []
    for lib in libs:
        for rel in (
            os.path.join("steamapps", "workshop", "content", WORKSHOP_APPID),
            os.path.join("workshop", "content", WORKSHOP_APPID),
        ):
            path = os.path.join(lib, rel)
            if os.path.isdir(path) and path not in out:
                out.append(path)
    return out


def myproject_dirs(libs: list[str]) -> list[str]:
    """Wallpaper Engine '我的壁纸'（我的项目）目录。"""
    out = []
    for lib in libs:
        for rel in (
            os.path.join("steamapps", "common", "wallpaper_engine", "projects", "myprojects"),
            os.path.join("common", "wallpaper_engine", "projects", "myprojects"),
        ):
            path = os.path.join(lib, rel)
            if os.path.isdir(path) and path not in out:
                out.append(path)
    for extra in _config.get("extra_project_dirs", []) or []:
        path = os.path.normpath(str(extra))
        if os.path.isdir(path) and path not in out:
            out.append(path)
    return out


def we_config_paths(libs: list[str]) -> list[str]:
    """Wallpaper Engine 的 config.json 位置（文件夹组织就存在里面）。"""
    out: list[str] = []
    extra = _config.get("we_config")
    if extra and os.path.isfile(str(extra)):
        out.append(os.path.normpath(str(extra)))
    for lib in libs:
        for rel in (
            os.path.join("steamapps", "common", "wallpaper_engine", "config.json"),
            os.path.join("common", "wallpaper_engine", "config.json"),
        ):
            path = os.path.join(lib, rel)
            if os.path.isfile(path) and path not in out:
                out.append(path)
    return out


def load_we_folders(libs: list[str]) -> dict:
    """读取 Wallpaper Engine「已安装 / 创意工坊」标签页里建立的文件夹树。

    返回 {"idToFolder": {id: 路径}, "idOrder": {id: 文件夹内序号},
          "folders": [{path,title,depth,order}], "config": 配置文件路径}
    """
    paths = we_config_paths(libs)
    result = {"idToFolder": {}, "idOrder": {}, "folders": [], "config": None}
    if not paths:
        return result
    try:
        path = max(paths, key=lambda p: os.path.getmtime(p))
    except OSError:
        path = paths[0]
    cfg = load_json(path, None)
    if not isinstance(cfg, dict):
        return result

    id_to_folder: dict[str, str] = {}
    id_order: dict[str, int] = {}
    folders: list[dict] = []
    counter = [0]

    def walk(node, prefix: list[str], depth: int) -> None:
        if not isinstance(node, dict):
            return
        title = str(node.get("title") or "").strip() or "未命名文件夹"
        parts = prefix + [title]
        full = " / ".join(parts)
        items = node.get("items")
        if isinstance(items, dict):
            for idx, wid in enumerate(items.keys()):
                wid = str(wid)
                # 同一个壁纸出现在多个文件夹时，以最先出现的（更靠上层）为准
                if wid not in id_to_folder:
                    id_to_folder[wid] = full
                    id_order[wid] = idx
        folders.append({"path": full, "title": title, "depth": depth, "order": counter[0]})
        counter[0] += 1
        for sub in node.get("subfolders") or []:
            walk(sub, parts, depth + 1)

    # config.json 里每个 Steam 账号一个 section，全部扫一遍
    for section in cfg.values():
        if not isinstance(section, dict):
            continue
        general = section.get("general")
        if not isinstance(general, dict):
            continue
        browser = general.get("browser")
        if not isinstance(browser, dict):
            continue
        for node in browser.get("folders") or []:
            walk(node, [], 0)

    result["idToFolder"] = id_to_folder
    result["idOrder"] = id_order
    result["folders"] = folders
    result["config"] = path
    log("读取 WE 文件夹：%d 个（%s），覆盖 %d 个壁纸 ID"
        % (len(folders), path, len(id_to_folder)))
    return result


# --------------------------------------------------------------------------
# MP4 / WebM 元数据探测（时长、分辨率）
# --------------------------------------------------------------------------


def _read_box_header(fh):
    head = fh.read(8)
    if len(head) < 8:
        return None
    size, btype = struct.unpack(">I4s", head)
    header_len = 8
    if size == 1:
        ext = fh.read(8)
        if len(ext) < 8:
            return None
        size = struct.unpack(">Q", ext)[0]
        header_len = 16
    elif size == 0:
        size = None
    try:
        name = btype.decode("latin1")
    except Exception:
        name = ""
    return size, name, header_len


def _parse_mvhd(payload: bytes):
    if len(payload) < 20:
        return None
    version = payload[0]
    try:
        if version == 1:
            timescale = struct.unpack(">I", payload[20:24])[0]
            duration = struct.unpack(">Q", payload[24:32])[0]
        else:
            timescale = struct.unpack(">I", payload[12:16])[0]
            duration = struct.unpack(">I", payload[16:20])[0]
    except struct.error:
        return None
    if not timescale:
        return None
    return duration / float(timescale)


def _parse_tkhd(payload: bytes):
    """只取宽高（16.16 定点），用于没有解析到视频轨道时兜底。"""
    version = payload[0] if payload else 0
    # version/flags(4) + creation + modification + track_ID + reserved + duration
    base = 4 + (8 + 8 + 4 + 4 + 8) if version == 1 else 4 + (4 + 4 + 4 + 4 + 4)
    # 之后：reserved(8) layer(2) alt(2) volume(2) reserved(2) matrix(36) width(4) height(4)
    off = base + 8 + 2 + 2 + 2 + 2 + 36
    if len(payload) < off + 8:
        return None
    try:
        w = struct.unpack(">I", payload[off:off + 4])[0] / 65536.0
        h = struct.unpack(">I", payload[off + 4:off + 8])[0] / 65536.0
    except struct.error:
        return None
    if w <= 0 or h <= 0:
        return None
    return (int(round(w)), int(round(h)))


def probe_mp4(path: str):
    """读取 mp4 的时长与分辨率；失败返回 (None, None, None)。"""
    duration = width = height = None
    try:
        file_size = os.path.getsize(path)
        with open(path, "rb") as fh:
            deadline = time.time() + 5.0
            while True:
                if time.time() > deadline:
                    break
                pos = fh.tell()
                if pos >= file_size:
                    break
                header = _read_box_header(fh)
                if not header:
                    break
                size, name, header_len = header
                if name == "moov":
                    moov_end = file_size if size is None else min(pos + size, file_size)
                    while fh.tell() < moov_end:
                        inner_pos = fh.tell()
                        inner = _read_box_header(fh)
                        if not inner:
                            break
                        isize, iname, iheader = inner
                        iend = moov_end if isize is None else min(inner_pos + isize, moov_end)
                        if iname == "mvhd":
                            payload = fh.read(max(0, iend - fh.tell()))
                            duration = _parse_mvhd(payload) or duration
                        elif iname == "trak":
                            trak_size = isize
                            trak_end = iend
                            while fh.tell() < trak_end:
                                tpos = fh.tell()
                                tbox = _read_box_header(fh)
                                if not tbox:
                                    break
                                tsize, tname, theader = tbox
                                tend = trak_end if tsize is None else min(tpos + tsize, trak_end)
                                if tname == "tkhd":
                                    payload = fh.read(max(0, tend - fh.tell()))
                                    dims = None
                                    try:
                                        dims = _parse_tkhd(payload)
                                    except Exception:
                                        dims = None
                                    if dims and not width:
                                        width, height = dims
                                fh.seek(tend)
                                if tsize is None:
                                    break
                            _ = trak_size
                        fh.seek(iend)
                        if isize is None:
                            break
                    break
                if size is None:
                    break
                fh.seek(pos + size)
    except OSError:
        pass
    except Exception as exc:  # 容错：任何解析异常都不影响使用
        log("probe 失败 %s: %s" % (path, exc))
    return duration, width, height


def probe_webm(path: str):
    """WebM 只做很轻量的时长探测（可失败）。"""
    try:
        import re as _re
        with open(path, "rb") as fh:
            head = fh.read(4096)
        if b"\x44\x89" in head:      # Duration element id
            return None
    except OSError:
        pass
    return None


# --------------------------------------------------------------------------
# 扫描
# --------------------------------------------------------------------------


def _key_for(source: str, ident: str) -> str:
    if source == "workshop":
        return "ws_" + re.sub(r"[^0-9A-Za-z]", "", ident)
    digest = hashlib.sha1(ident.encode("utf-8", "ignore")).hexdigest()[:10]
    return "my_" + digest


def _pick_video(folder: str, project: dict) -> str | None:
    declared = str(project.get("file") or "").strip()
    candidates: list[str] = []
    if declared:
        cand = os.path.join(folder, declared.replace("/", os.sep))
        if os.path.isfile(cand) and os.path.splitext(cand)[1].lower() in VIDEO_EXT:
            candidates.append(cand)
    try:
        for entry in os.scandir(folder):
            if entry.is_file() and os.path.splitext(entry.name)[1].lower() in VIDEO_EXT:
                if entry.path not in candidates:
                    candidates.append(entry.path)
    except OSError:
        pass
    if not candidates:
        return None
    # 优先 mp4/webm（浏览器能播），其次按体积从大到小
    def sort_key(p: str):
        ext = os.path.splitext(p)[1].lower()
        try:
            size = os.path.getsize(p)
        except OSError:
            size = 0
        return (0 if ext in BROWSER_VIDEO_EXT else 1, -size)
    candidates.sort(key=sort_key)
    return candidates[0]


def _pick_preview(folder: str, project: dict) -> tuple[str | None, str]:
    declared = str(project.get("preview") or "").strip()
    names: list[str] = []
    if declared:
        names.append(declared.replace("/", os.sep))
    names.extend(["preview.gif", "preview.jpg", "preview.jpeg", "preview.png", "preview.webp"])
    for name in names:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            ext = os.path.splitext(path)[1].lower()
            if ext in PREVIEW_EXT:
                return path, ("gif" if ext == ".gif" else "image")
    # 退一步：目录里任意图片
    try:
        for entry in os.scandir(folder):
            if entry.is_file() and os.path.splitext(entry.name)[1].lower() in PREVIEW_EXT:
                ext = os.path.splitext(entry.name)[1].lower()
                return entry.path, ("gif" if ext == ".gif" else "image")
    except OSError:
        pass
    return None, "none"


def _folder_size(folder: str) -> int:
    total = 0
    try:
        for root, _dirs, files in os.walk(folder):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    continue
    except OSError:
        pass
    return total


def _folder_mtime(folder: str) -> float:
    newest = 0.0
    try:
        newest = os.path.getmtime(folder)
        for entry in os.scandir(folder):
            try:
                newest = max(newest, entry.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        pass
    return newest


def build_item(folder: str, source: str, ident: str, project: dict | None,
               we_info: dict | None = None) -> dict | None:
    project = project or {}
    video = _pick_video(folder, project)
    preview, preview_kind = _pick_preview(folder, project)
    if not video and not preview:
        return None

    raw_type = str(project.get("type") or "").lower()
    if not raw_type:
        raw_type = "video" if video else "scene"
    if raw_type not in TYPE_LABELS:
        raw_type = "video" if video else "scene"

    title = str(project.get("title") or "").strip()
    if not title:
        title = os.path.basename(folder)

    tags = project.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    tags = [str(t) for t in tags if str(t).strip()]

    key = _key_for(source, ident)
    ext = os.path.splitext(video)[1].lower() if video else ""
    browser_playable = bool(video) and ext in BROWSER_VIDEO_EXT

    duration = width = height = None
    if video and ext == ".mp4":
        cached = _cache.get(video)
        try:
            stat = os.stat(video)
            sig = [int(stat.st_size), int(stat.st_mtime)]
        except OSError:
            sig = [0, 0]
        if cached and cached.get("sig") == sig:
            duration, width, height = cached.get("duration"), cached.get("w"), cached.get("h")
        else:
            duration, width, height = probe_mp4(video)
            _cache[video] = {"sig": sig, "duration": duration, "w": width, "h": height}
    elif video:
        probe_webm(video)

    try:
        video_size = os.path.getsize(video) if video else 0
    except OSError:
        video_size = 0

    # ---- Wallpaper Engine 文件夹归属 + 订阅（下载）时间 ----
    folder_path = ""
    folder_order = 10 ** 6
    folder_depth = 0
    we_order = 10 ** 6
    if source == "workshop" and we_info:
        folder_path = we_info.get("idToFolder", {}).get(ident, "")
        we_order = we_info.get("idOrder", {}).get(ident, 10 ** 6)
        if folder_path:
            for meta in we_info.get("folders", []):
                if meta["path"] == folder_path:
                    folder_order = meta["order"]
                    folder_depth = meta["depth"]
                    break
    elif source == "myproject":
        folder_path = "我的壁纸"
        folder_order = -1
    try:
        subscribed_at = os.stat(folder).st_ctime      # 目录创建时间 ≈ 订阅下载时间
    except OSError:
        subscribed_at = 0.0

    return {
        "key": key,
        "id": ident,
        "source": source,
        "sourceLabel": "创意工坊" if source == "workshop" else "我的壁纸",
        "type": raw_type,
        "typeLabel": TYPE_LABELS.get(raw_type, raw_type),
        "title": title,
        "tags": tags,
        "rating": str(project.get("contentrating") or ""),
        "description": str(project.get("description") or "").strip(),
        "workshopUrl": str(project.get("workshopurl") or ""),
        "folder": folder,                 # 壁纸在磁盘上的目录
        "weFolder": folder_path,          # Wallpaper Engine 里的文件夹路径（可能为空=未分类）
        "weFolderName": folder_path.split(" / ")[-1] if folder_path else "",
        "weFolderOrder": folder_order,
        "weFolderDepth": folder_depth,
        "weOrder": we_order,              # 在 WE 文件夹内的排列序号
        "subscribedAt": subscribed_at,    # 订阅/下载时间（目录创建时间）
        "hasVideo": bool(video),
        "browserPlayable": browser_playable,
        "videoExt": ext,
        "duration": duration,
        "width": width,
        "height": height,
        "previewKind": preview_kind,
        "size": _folder_size(folder),
        "videoSize": video_size,
        "mtime": _folder_mtime(folder),
        "_video": video,
        "_preview": preview,
    }


def public_item(item: dict) -> dict:
    out = {k: v for k, v in item.items() if not k.startswith("_")}
    key = out["key"]
    out["previewUrl"] = "/preview/%s" % key if item.get("_preview") else None
    out["mediaUrl"] = "/media/%s" % key if item.get("_video") else None
    out["sizeText"] = human_size(out.get("size") or 0)
    if out.get("duration"):
        out["durationText"] = time.strftime(
            "%H:%M:%S" if out["duration"] >= 3600 else "%M:%S", time.gmtime(out["duration"])
        )
    else:
        out["durationText"] = None
    if out.get("width") and out.get("height"):
        out["resolutionText"] = "%d × %d" % (out["width"], out["height"])
    else:
        out["resolutionText"] = None
    return out


def scan_library(force: bool = False) -> dict:
    """扫描所有 Steam 库，重建壁纸索引。"""
    global _items, _items_order, _cache
    started = time.time()
    with _lock:
        if force:
            _cache = {}

    libs = discover_steam_libraries()
    ws_dirs = workshop_dirs(libs)
    my_dirs = myproject_dirs(libs)
    we_info = load_we_folders(libs)

    items: dict[str, dict] = {}
    errors: list[str] = []

    for ws in ws_dirs:
        try:
            entries = [e for e in os.scandir(ws) if e.is_dir()]
        except OSError as exc:
            errors.append("无法读取 %s: %s" % (ws, exc))
            continue
        for entry in entries:
            pj = os.path.join(entry.path, "project.json")
            if not os.path.isfile(pj):
                continue
            project = load_json(pj, None)
            if not isinstance(project, dict):
                continue
            try:
                item = build_item(entry.path, "workshop", entry.name, project, we_info)
            except Exception as exc:
                errors.append("%s 解析失败: %s" % (entry.name, exc))
                continue
            if item:
                items[item["key"]] = item

    for base in my_dirs:
        for root, dirs, files in os.walk(base):
            depth = os.path.relpath(root, base).count(os.sep)
            if depth > 2:
                dirs[:] = []
                continue
            if "project.json" in files:
                project = load_json(os.path.join(root, "project.json"), {})
                if not isinstance(project, dict):
                    project = {}
                ident = os.path.relpath(root, base).replace("\\", "/")
                try:
                    item = build_item(root, "myproject", ident, project, we_info)
                except Exception as exc:
                    errors.append("%s 解析失败: %s" % (ident, exc))
                    continue
                if item:
                    items[item["key"]] = item
                dirs[:] = []

    order = sorted(items.keys(), key=lambda k: items[k]["mtime"], reverse=True)
    with _lock:
        _items = items
        _items_order = order
        save_json(CACHE_FILE, _cache)

    # 只保留真正含有已下载壁纸的 WE 文件夹（含层级关系）
    used_paths = {i["weFolder"] for i in items.values() if i.get("weFolder")}
    folder_nodes = [
        f for f in we_info.get("folders", [])
        if any(p == f["path"] or p.startswith(f["path"] + " / ") for p in used_paths)
    ]
    counts: dict[str, int] = {}
    for i in items.values():
        if i.get("weFolder"):
            counts[i["weFolder"]] = counts.get(i["weFolder"], 0) + 1

    stats = {
        "workshopDirs": ws_dirs,
        "myProjectDirs": my_dirs,
        "libraries": libs,
        "total": len(items),
        "video": sum(1 for i in items.values() if i["hasVideo"]),
        "browserPlayable": sum(1 for i in items.values() if i["browserPlayable"]),
        "weConfig": we_info.get("config"),
        "weFolders": [
            {"path": f["path"], "title": f["title"], "depth": f["depth"],
             "count": counts.get(f["path"], 0)}
            for f in folder_nodes
        ],
        "unclassified": sum(1 for i in items.values() if not i.get("weFolder")),
        "seconds": round(time.time() - started, 2),
        "errors": errors,
    }
    log("扫描完成：%d 个壁纸（视频 %d），WE 文件夹 %d 个，未分类 %d，耗时 %.2fs"
        % (stats["total"], stats["video"], len(stats["weFolders"]),
           stats["unclassified"], stats["seconds"]))
    return stats


# --------------------------------------------------------------------------
# Wallpaper Engine 效果窗口
#
# 场景（scene）/ 网页（web）壁纸是 Wallpaper Engine 自己的渲染格式，我们没法
# 自己解析。官方提供了命令行：
#     wallpaper32.exe -control openWallpaper -file <project.json>
#                    -playInWindow <窗口名> [-width W] [-height H] [-x X] [-y Y]
#                    [-borderless] [-activate]
# 可以让 WE 把壁纸渲染到一个独立窗口里。我们再用 SetWindowPos 把这个窗口
# 精确贴在播放器的画面上，并在播放器失焦时隐藏它 —— 看起来就像内嵌播放。
# --------------------------------------------------------------------------

EFFECT_WINDOW_NAME = "WEPlayerEffect"
EFFECT_TITLE_HINT = "壁纸播放器"

_USER32 = None
_effect_state = {"key": None, "hwnd": 0, "visible": False, "rect": None}
_effect_lock = threading.RLock()


def _user32():
    """懒加载 user32（顺带把参数类型声明好，避免 64 位下指针被截断）。"""
    global _USER32
    if _USER32 is not None:
        return _USER32
    if sys.platform != "win32":
        _USER32 = False
        return False
    import ctypes
    from ctypes import wintypes

    u = ctypes.WinDLL("user32", use_last_error=True)
    u.FindWindowW.restype = wintypes.HWND
    u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    u.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.IsWindow.argtypes = [wintypes.HWND]
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    u.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    u.GetForegroundWindow.restype = wintypes.HWND
    _USER32 = u
    return u


def _find_window(title_exact: str = "", title_contains: str = "", class_name: str = "",
                 title_endswith: str = "", prefer_foreground: bool = False) -> int:
    """按标题/类名找顶层窗口，返回 hwnd（0 表示没找到）。

    播放器窗口的标题形如 "WE 壁纸播放器" 或 "Klee - Trip — WE 壁纸播放器"，
    用 endswith 匹配可以避免把标题里恰好含这几个字的其它窗口认错。
    """
    u = _user32()
    if not u:
        return 0
    import ctypes
    from ctypes import wintypes

    hits: list[int] = []

    def _cb(hwnd, _lparam):
        buf = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(hwnd, buf, 512)
        title = buf.value
        if not title:
            return True
        cbuf = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, cbuf, 256)
        if title_exact and title != title_exact:
            return True
        if title_contains and title_contains not in title:
            return True
        if title_endswith and not title.endswith(title_endswith):
            return True
        if class_name and cbuf.value != class_name:
            return True
        hits.append(int(hwnd))
        return True

    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(_cb)
    u.EnumWindows(ctypes.cast(proc, ctypes.c_void_p), 0)
    if not hits:
        return 0
    if prefer_foreground:
        fg = int(u.GetForegroundWindow())
        if fg in hits:
            return fg
    return hits[0]


def _window_alive(hwnd: int) -> bool:
    u = _user32()
    return bool(u) and bool(hwnd) and bool(u.IsWindow(hwnd))


def we_executable() -> str | None:
    """定位 wallpaper32.exe / wallpaper64.exe，优先与正在运行的实例同位数。"""
    libs = discover_steam_libraries()
    found: dict[str, str] = {}
    for lib in libs:
        for rel in (os.path.join("steamapps", "common", "wallpaper_engine"),
                    os.path.join("common", "wallpaper_engine")):
            base = os.path.join(lib, rel)
            for exe in ("wallpaper32.exe", "wallpaper64.exe"):
                path = os.path.join(base, exe)
                if os.path.isfile(path):
                    found.setdefault(exe, path)
    override = _config.get("we_executable")
    if override and os.path.isfile(str(override)):
        return os.path.normpath(str(override))
    if not found:
        return None
    preferred = "wallpaper32.exe" if we_process_running("wallpaper32") else (
        "wallpaper64.exe" if we_process_running("wallpaper64") else "wallpaper32.exe")
    return found.get(preferred) or found.get("wallpaper64.exe") or found.get("wallpaper32.exe")


def we_process_running(name: str = "wallpaper32") -> bool:
    """检测 WE 进程是否在运行（tasklist 解析，取不到就返回 False）。"""
    try:
        proc = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s.exe" % name, "/NH"],
                              capture_output=True, timeout=6,
                              creationflags=0x08000000)
        out = (proc.stdout or b"").decode("utf-8", "ignore").lower()
        return ("%s.exe" % name) in out
    except Exception:
        return False


def _we_control(args: list[str]) -> bool:
    exe = we_executable()
    if not exe:
        return False
    try:
        subprocess.run([exe, "-control"] + args, capture_output=True, timeout=15,
                       creationflags=0x08000000)
        return True
    except Exception as exc:
        log("WE 命令失败 %s: %s" % (args, exc))
        return False


def _effect_geometry(rect: dict, dpr: float, player: int = 0):
    """把页面给的 CSS 像素矩形换算成屏幕物理像素（以播放器窗口客户区为基准）。"""
    try:
        left = float(rect.get("left", 0))
        top = float(rect.get("top", 0))
        width = float(rect.get("width", 0))
        height = float(rect.get("height", 0))
    except (TypeError, ValueError):
        return None
    if width < 32 or height < 32:
        return None
    dpr = float(dpr or 1.0) or 1.0
    if not player:
        player = _find_window(title_endswith=EFFECT_TITLE_HINT, class_name="Chrome_WidgetWin_1",
                              prefer_foreground=True)
    if not player:
        player = _find_window(title_endswith=EFFECT_TITLE_HINT, prefer_foreground=True)
    origin = None
    if player:
        u = _user32()
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT(0, 0)
        if u.ClientToScreen(player, ctypes.byref(pt)):
            origin = (pt.x, pt.y)
    if origin is None:
        # 兜底：用页面报告的窗口屏幕坐标
        try:
            origin = (round(float(rect.get("screenX", 0)) * dpr),
                      round(float(rect.get("screenY", 0)) * dpr))
        except (TypeError, ValueError):
            return None
    x = origin[0] + round(left * dpr)
    y = origin[1] + round(top * dpr)
    return x, y, round(width * dpr), round(height * dpr)


def _effect_auto_visible(player_hwnd: int, effect_hwnd: int):
    """由前台窗口决定效果窗口该不该显示。

    - 播放器在前台 → 显示
    - 用户点了画面（效果窗口自己变成前台）→ 也保持显示
    - 切到别的程序（游戏、浏览器…）→ 隐藏，免得一个置顶窗口飘在人家上面
    """
    u = _user32()
    if not u:
        return None
    fg = int(u.GetForegroundWindow())
    if not fg:
        return None
    if player_hwnd and fg == player_hwnd:
        return True
    if effect_hwnd and fg == effect_hwnd:
        return True
    return False


def position_effect_window(rect: dict, dpr: float, visible=None, focused=None) -> dict:
    """把效果窗口移动到指定矩形；visible=None 时按前台窗口自动判断。"""
    u = _user32()
    if not u:
        return {"ok": False, "error": "仅支持 Windows"}
    with _effect_lock:
        hwnd = _effect_state.get("hwnd") or _find_window(title_exact=EFFECT_WINDOW_NAME)
        if not _window_alive(hwnd):
            _effect_state["hwnd"] = 0
            return {"ok": False, "error": "效果窗口不存在"}
        _effect_state["hwnd"] = hwnd
        player = _find_window(title_endswith=EFFECT_TITLE_HINT, class_name="Chrome_WidgetWin_1")
        if not player:
            player = _find_window(title_endswith=EFFECT_TITLE_HINT)
        if visible is None:
            auto = _effect_auto_visible(player, hwnd)
            if focused is True:
                visible = True          # 页面自己说它在前台，那就是前台
            elif auto is None:
                visible = True
            else:
                visible = auto
        visible = bool(visible)
        geo = _effect_geometry(rect or {}, dpr, player) if rect else None
        HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
        SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
        SWP_SHOWWINDOW, SWP_HIDEWINDOW = 0x0040, 0x0080
        if geo:
            x, y, w, h = geo
        else:
            x = y = w = h = 0
        flags = SWP_NOACTIVATE | (SWP_SHOWWINDOW if visible else SWP_HIDEWINDOW)
        if not geo:
            flags |= SWP_NOMOVE | SWP_NOSIZE
        if not u.SetWindowPos(hwnd, HWND_TOPMOST if visible else HWND_NOTOPMOST,
                              x, y, w, h, flags):
            return {"ok": False, "error": "SetWindowPos 失败"}
        _effect_state["visible"] = visible
        if geo:
            _effect_state["rect"] = geo
        return {"ok": True, "rect": _effect_state.get("rect"), "visible": visible,
                "debug": {"foreground": int(u.GetForegroundWindow()), "player": int(player),
                          "effect": int(hwnd)}}


def open_effect_window(item: dict, rect: dict, dpr: float) -> dict:
    """让 Wallpaper Engine 把这张壁纸渲染到效果窗口，并贴到播放器画面上。"""
    if not _user32():
        return {"ok": False, "error": "仅支持 Windows"}
    if os.environ.get("WE_PLAYER_NO_EFFECT"):
        return {"ok": False, "error": "已通过环境变量禁用效果窗口"}
    exe = we_executable()
    if not exe:
        return {"ok": False, "error": "没有找到 wallpaper32.exe / wallpaper64.exe"}

    target = os.path.join(item.get("folder", ""), "project.json")
    if not os.path.isfile(target):
        target = item.get("_video") or ""
    if not target or not os.path.isfile(target):
        return {"ok": False, "error": "找不到该壁纸的 project.json"}

    if not we_process_running("wallpaper32") and not we_process_running("wallpaper64"):
        return {"ok": False, "error": "Wallpaper Engine 没有在运行"}

    geo = _effect_geometry(rect or {}, dpr) or (0, 0, 960, 540)
    x, y, w, h = geo
    # CLI 的 -width/-height 比实际窗口小 16x39（WE 自己加的边距），这里补偿一下，
    # 之后还会用 SetWindowPos 精确校正。
    args = ["openWallpaper", "-file", target, "-playInWindow", EFFECT_WINDOW_NAME,
            "-width", str(max(64, w - 16)), "-height", str(max(64, h - 39)),
            "-x", str(x), "-y", str(y), "-borderless"]
    reusing = _window_alive(_effect_state.get("hwnd") or 0) or bool(
        _find_window(title_exact=EFFECT_WINDOW_NAME))
    try:
        subprocess.Popen([exe, "-control"] + args, close_fds=True,
                         creationflags=0x08000000)
    except Exception as exc:
        return {"ok": False, "error": "启动 WE 失败：%s" % exc}

    hwnd = 0
    deadline = time.time() + 8.0
    while time.time() < deadline:
        hwnd = _find_window(title_exact=EFFECT_WINDOW_NAME)
        if hwnd:
            break
        time.sleep(0.15)
    if not hwnd:
        return {"ok": False, "error": "Wallpaper Engine 没有建立效果窗口"}

    with _effect_lock:
        _effect_state.update({"key": item.get("key"), "hwnd": hwnd, "visible": True})

    # 等 WE 把壁纸加载出来再精确定位，避免定位被它后续的布局覆盖
    time.sleep(0.6 if reusing else 1.2)
    out = position_effect_window(rect, dpr, visible=True)
    log("效果窗口：%s（%s）%s" % (item.get("title"), item.get("key"),
                                 "复用" if reusing else "新建"))
    return {"ok": True, "reused": reusing, "rect": out.get("rect")}


def close_effect_window() -> dict:
    """关闭效果窗口（离开壁纸、切换视频壁纸、退出程序时调用）。"""
    with _effect_lock:
        hwnd = _effect_state.get("hwnd") or _find_window(title_exact=EFFECT_WINDOW_NAME)
        if _window_alive(hwnd):
            _user32().ShowWindow(hwnd, 0)      # 先藏起来，避免关闭动画残留
        _effect_state.update({"key": None, "hwnd": 0, "visible": False, "rect": None})
    _we_control(["closeWallpaper", "-location", EFFECT_WINDOW_NAME])
    return {"ok": True}


# --------------------------------------------------------------------------
# 开发用最坏数据夹具（只在 --dev 下通过 /api/library?data=... 暴露）
#
# 这些值都来自真实世界：Steam 创意工坊标题确实会出现超长连字符文件名、中日英
# 混排、emoji、<by xxx> 这种尖括号，WE 的文件夹名是用户自己起的（无长度限制），
# 预览图确实可能缺失。夹具用来在改动 UI 后回归「最坏数据下会不会破」。
# --------------------------------------------------------------------------


def _fx(key, title, **kw):
    item = {
        "key": key, "id": key.split("_")[-1], "source": "workshop", "sourceLabel": "创意工坊",
        "type": "video", "typeLabel": "视频壁纸", "title": title,
        "tags": [], "rating": "Everyone", "description": "", "workshopUrl": "",
        "weFolder": "", "weFolderName": "", "weFolderOrder": 10 ** 6, "weFolderDepth": 0,
        "weOrder": 10 ** 6, "subscribedAt": 0,
        "hasVideo": True, "browserPlayable": True, "videoExt": ".mp4",
        "duration": 900.0, "width": 1920, "height": 1080, "previewKind": "gif",
        "size": 100 * 1024 * 1024, "videoSize": 100 * 1024 * 1024, "mtime": 0,
        "folder": r"G:\SteamLibrary\steamapps\workshop\content\431960\%s" % item_id(key),
        "previewUrl": "/preview/%s" % key, "mediaUrl": "/media/%s" % key,
    }
    item.update(kw)
    return item


def item_id(key):
    return key.split("_")[-1]


def dev_fixtures(kind: str):
    """返回 (items, stats)；kind 见下方分支。"""
    kind = (kind or "").lower()

    def polish(items):
        for it in items:
            it["sizeText"] = human_size(it.get("size") or 0)
            d = it.get("duration")
            it["durationText"] = time.strftime(
                "%H:%M:%S" if d and d >= 3600 else "%M:%S", time.gmtime(d)) if d else None
            if it.get("width") and it.get("height"):
                it["resolutionText"] = "%d × %d" % (it["width"], it["height"])
            else:
                it["resolutionText"] = None
        return items

    long_folder = "18 / Anime-Wallpapers-Collection-2024-2026-4K-HDR-60fps-Collection"

    if kind == "empty":
        return [], {"total": 0, "video": 0, "browserPlayable": 0, "seconds": 0,
                    "weFolders": [], "unclassified": 0, "libraries": [], "workshopDirs": [],
                    "myProjectDirs": [], "errors": [], "dev": True}

    if kind == "one":
        items = [_fx("ws_1", "Klee - Trip", weFolder="18", weFolderName="18")]
        return polish(items), {"total": 1, "video": 1, "browserPlayable": 1, "seconds": 0,
                               "weFolders": [{"path": "18", "title": "18", "depth": 0, "count": 1}],
                               "unclassified": 0, "libraries": [], "workshopDirs": [],
                               "myProjectDirs": [], "errors": [], "dev": True}

    if kind == "many":                       # 1,284 条：计数格式 + 滚动性能
        items = []
        for i in range(1284):
            items.append(_fx("ws_%d" % (900000000 + i),
                             "Wallpaper %d — 长标题回归样本 %04d" % (i + 1, i + 1),
                             weFolder="18" if i % 2 else "", weFolderName="18" if i % 2 else ""))
        return polish(items), {"total": 1284, "video": 1284, "browserPlayable": 1284, "seconds": 0,
                               "weFolders": [{"path": "18", "title": "18", "depth": 0, "count": 642}],
                               "unclassified": 642, "libraries": [], "workshopDirs": [],
                               "myProjectDirs": [], "errors": [], "dev": True}

    if kind != "worst":
        return None

    items = [
        # 1) 超长「文件名式」标题：连字符是换行点，但没有空格
        _fx("ws_900000001",
            "wallpaperwaifu.com-Saber-Alter-Fate-Stay-Night-Heaven's-Feel-Desktop-4K-2160p-60fps-remaster-final-v12",
            weFolder=long_folder, weFolderName="Anime-Wallpapers-Collection-2024-2026-4K-HDR-60fps-Collection",
            size=int(12.4 * 1024 ** 3), duration=7199.0, width=3840, height=2160),
        # 2) 中日英混排 + emoji + 全角括号 + 组合 emoji
        _fx("ws_900000002", "【我推的孩子】星野アイ＆星野るびい 👩🏽‍💻 4K HDR 60FPS 修正版（rev.3）[期間限定]",
            weFolder=long_folder, weFolderName="Anime-Wallpapers-Collection-2024-2026-4K-HDR-60fps-Collection",
            size=int(1.9 * 1024 ** 3), duration=3725.0, width=3840, height=2160),
        # 3) 尖括号 / & / 引号：转义必须是字面量
        _fx("ws_900000003", "[4K] M4 SOPMOD II (from Girls' Frontline) <by SD Big Pie> & \"friends\"",
            size=int(59.2 * 1024 ** 2), duration=63.0, width=1920, height=1080),
        # 4) 极短标题 + 中文单字：列看起来很空
        _fx("ws_900000004", "囍", size=int(95.4 * 1024 ** 2), duration=23.0, width=2560, height=1440),
        _fx("ws_900000005", "A", size=int(2.1 * 1024 ** 2), duration=4.0, width=640, height=360),
        # 5) 可选字段全缺：没有时长/分辨率/文件夹/分级，只剩体积
        _fx("ws_900000006", "Untitled", hasVideo=False, browserPlayable=False, type="scene",
            typeLabel="场景壁纸", videoExt="", duration=None, width=None, height=None,
            rating="", size=int(1.2 * 1024 ** 2)),
        # 6) 超长不可断的标签名（侧栏 chip 的宽度上限）
        _fx("ws_900000007", "Tag wall sample", size=int(30 * 1024 ** 2), duration=120.0,
            tags=["customer-feedback-from-enterprise-onboarding", "design", "frontend", "q3",
                  "urgent", "needs-review", "4k", "anime", "loop", "audio-responsive",
                  "mobile-compatible", "customizable"],
            weFolder=long_folder, weFolderName="Anime-Wallpapers-Collection-2024-2026-4K-HDR-60fps-Collection"),
        # 7) 预览图 404：必须回退到占位图，不能是碎图图标
        _fx("ws_900000008", "Broken preview wallpaper", previewUrl="/preview/ws_does_not_exist",
            size=int(70 * 1024 ** 2), duration=180.0),
        # 8) 极端时长/体积/超宽分辨率
        _fx("ws_900000009", "10 hours loop — 8K 超宽屏", size=int(48.7 * 1024 ** 3),
            duration=35999.0, width=7680, height=1080),
        # 9) 「我的壁纸」来源 + 无时长（长跑动的字段错位）
        _fx("ws_900000010", "ローカルで作った壁紙（自分用）", source="myproject",
            sourceLabel="我的壁纸", weFolder="我的壁纸", weFolderName="我的壁纸",
            hasVideo=False, browserPlayable=False, type="web", typeLabel="网页壁纸",
            videoExt="", duration=None, width=None, height=None, size=int(3.4 * 1024 ** 2)),
    ]
    counts = {}
    for it in items:
        if it["weFolder"]:
            counts[it["weFolder"]] = counts.get(it["weFolder"], 0) + 1
    stats = {
        "total": len(items), "video": sum(1 for i in items if i["hasVideo"]),
        "browserPlayable": sum(1 for i in items if i["browserPlayable"]),
        "weFolders": [{"path": long_folder, "title": long_folder.split(" / ")[-1],
                       "depth": 1, "count": counts.get(long_folder, 0)},
                      {"path": "我的壁纸", "title": "我的壁纸", "depth": 0, "count": 1}],
        "unclassified": sum(1 for i in items if not i["weFolder"]),
        "seconds": 0, "libraries": [], "workshopDirs": [], "myProjectDirs": [], "errors": [],
        "dev": True,
    }
    return polish(items), stats


# --------------------------------------------------------------------------
# 状态
# --------------------------------------------------------------------------


DEFAULT_STATE = {
    "favorites": {},
    "positions": {},
    "watched": {},
    "settings": {},
}


def load_state() -> dict:
    global _state, _config, _cache
    ensure_dirs()
    state = load_json(STATE_FILE, None)
    if not isinstance(state, dict):
        state = {}
    merged = dict(DEFAULT_STATE)
    for key, val in state.items():
        merged[key] = val
    for key, val in DEFAULT_STATE.items():
        if not isinstance(merged.get(key), dict):
            merged[key] = dict(val)
    _state = merged
    _config = load_json(CONFIG_FILE, {}) or {}
    if not isinstance(_config, dict):
        _config = {}
    _cache = load_json(CACHE_FILE, {}) or {}
    if not isinstance(_cache, dict):
        _cache = {}
    return _state


def apply_state_patch(patch: dict) -> dict:
    with _lock:
        for section in ("favorites", "positions", "watched", "settings"):
            data = patch.get(section)
            if isinstance(data, dict):
                for key, val in data.items():
                    if val is None:
                        _state[section].pop(key, None)
                    else:
                        _state[section][key] = val
        save_json(STATE_FILE, _state)
    return _state


# --------------------------------------------------------------------------
# HTTP 服务
# --------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "WEPlayer/1.0"
    protocol_version = "HTTP/1.1"

    # ---------- 基础工具 ----------
    def log_message(self, fmt, *args):  # 静音默认日志
        return

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, val in (extra or {}).items():
            self.send_header(key, val)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _json(self, data, code: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _read_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        try:
            raw = self.rfile.read(length)
        except OSError:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _query(self) -> dict:
        parsed = urllib.parse.urlparse(self.path)
        return {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}

    def _path(self) -> str:
        return urllib.parse.unquote(urllib.parse.urlparse(self.path).path)

    def _item(self, key: str) -> dict | None:
        with _lock:
            return _items.get(key)

    # ---------- 静态资源 ----------
    def _serve_static(self, rel: str) -> bool:
        rel = rel.lstrip("/") or "index.html"
        target = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not target.startswith(os.path.normpath(WEB_DIR)):
            return False
        if not os.path.isfile(target):
            return False
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        try:
            with open(target, "rb") as fh:
                body = fh.read()
        except OSError:
            return False
        self._send(200, body, ctype)
        return True

    def _serve_file(self, path: str | None, ctype: str | None = None, allow_range: bool = False) -> None:
        if not path or not os.path.isfile(path):
            self._json({"error": "文件不存在"}, 404)
            return
        ctype = ctype or mimetypes.guess_type(path)[0] or "application/octet-stream"
        try:
            size = os.path.getsize(path)
        except OSError:
            self._json({"error": "无法读取文件"}, 500)
            return
        start, end = 0, size - 1
        range_header = self.headers.get("Range")
        partial = False
        if allow_range and range_header:
            match = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
            if match:
                if match.group(1):
                    start = int(match.group(1))
                    if match.group(2):
                        end = int(match.group(2))
                elif match.group(2):
                    start = max(0, size - int(match.group(2)))
                end = min(end, size - 1)
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % size)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                partial = True
        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if partial:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = fh.read(min(262144, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except OSError as exc:
            log("发送文件中断 %s: %s" % (path, exc))

    # ---------- 路由 ----------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        global _last_ping, _seen_ping
        _last_ping = time.time()
        _seen_ping = True
        path = self._path()

        if path in ("/", "/index.html", "/player"):
            if self._serve_static("index.html"):
                return
            self._send(500, b"web/index.html missing", "text/plain; charset=utf-8")
            return

        if path == "/api/ping":
            _last_ping = time.time()
            _seen_ping = True
            self._json({"ok": True, "t": _last_ping})
            return

        if path == "/api/library":
            kind = self._query().get("data") if DEV_MODE else None
            if kind:
                fixture = dev_fixtures(kind)
                if fixture is not None:
                    items, stats = fixture
                    self._json({"items": items, "state": _state, "stats": stats, "dev": True})
                    return
            with _lock:
                items = [public_item(_items[k]) for k in _items_order if k in _items]
            self._json({"items": items, "state": _state,
                        "stats": dict(_stats, dev=bool(DEV_MODE))})
            return

        if path == "/api/state":
            self._json(_state)
            return

        if path.startswith("/preview/"):
            item = self._item(path[len("/preview/"):])
            if not item:
                self._json({"error": "未知壁纸"}, 404)
                return
            self._serve_file(item.get("_preview"))
            return

        if path.startswith("/media/"):
            item = self._item(path[len("/media/"):])
            if not item or not item.get("_video"):
                self._json({"error": "未知壁纸"}, 404)
                return
            self._serve_file(item["_video"], allow_range=True)
            return

        if path.startswith("/file/"):
            # 辅助：按 key 直接取原始路径（仅返回 JSON，不做任意路径读取）
            item = self._item(path[len("/file/"):])
            self._json({"path": (item or {}).get("_video")})
            return

        if self._serve_static(path):
            return

        self._json({"error": "not found"}, 404)

    def do_POST(self):
        global _last_ping, _seen_ping, _stats
        _last_ping = time.time()
        _seen_ping = True
        path = self._path()
        body = self._read_body()

        if path == "/api/ping":
            _last_ping = time.time()
            _seen_ping = True
            self._json({"ok": True})
            return

        if path == "/api/state":
            self._json(apply_state_patch(body))
            return

        if path == "/api/duration":
            key = str(body.get("key") or "")
            seconds = body.get("seconds")
            item = self._item(key)
            if item and item.get("_video") and isinstance(seconds, (int, float)) and seconds > 0:
                with _lock:
                    _items[key]["duration"] = float(seconds)
                    try:
                        stat = os.stat(item["_video"])
                        _cache[item["_video"]] = {
                            "sig": [int(stat.st_size), int(stat.st_mtime)],
                            "duration": float(seconds),
                            "w": item.get("width"),
                            "h": item.get("height"),
                        }
                        save_json(CACHE_FILE, _cache)
                    except OSError:
                        pass
            self._json({"ok": True})
            return

        if path == "/api/rescan":
            _stats = scan_library(force=bool(body.get("force")))
            self._json({"ok": True, "stats": _stats})
            return

        if path == "/api/reveal":
            item = self._item(str(body.get("key") or ""))
            target = (item or {}).get("_video") or (item or {}).get("folder")
            ok = False
            if target and os.path.exists(target):
                try:
                    if os.path.isfile(target):
                        subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
                    else:
                        os.startfile(os.path.normpath(target))  # type: ignore[attr-defined]
                    ok = True
                except Exception as exc:
                    log("reveal 失败: %s" % exc)
            self._json({"ok": ok})
            return

        if path == "/api/open_external":
            item = self._item(str(body.get("key") or ""))
            target = (item or {}).get("_video")
            ok = False
            if target and os.path.isfile(target):
                try:
                    os.startfile(os.path.normpath(target))  # type: ignore[attr-defined]
                    ok = True
                except Exception as exc:
                    log("外部播放失败: %s" % exc)
            self._json({"ok": ok})
            return

        if path == "/api/effect/open":
            item = self._item(str(body.get("key") or ""))
            if not item:
                self._json({"ok": False, "error": "未知壁纸"}, 404)
                return
            result = open_effect_window(item, body.get("rect") or {}, body.get("dpr") or 1.0)
            self._json(result)
            return

        if path == "/api/effect/update":
            self._json(position_effect_window(body.get("rect") or {},
                                              body.get("dpr") or 1.0,
                                              body.get("visible", None),
                                              body.get("focused", None)))
            return

        if path == "/api/effect/close":
            self._json(close_effect_window())
            return

        if path == "/api/shutdown":
            self._json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return

        if path == "/api/bye":
            self._json({"ok": True})
            if AUTO_CLOSE:
                threading.Thread(target=_delayed_shutdown, args=(10.0,), daemon=True).start()
            return

        self._json({"error": "not found"}, 404)


def _delayed_shutdown(delay: float) -> None:
    """页面关闭后延迟退出；若期间有新页面 ping，则取消退出。"""
    global _last_ping
    mark = time.time()
    time.sleep(delay)
    if _last_ping >= mark:
        return
    _quit_server("播放器窗口已关闭")


def _quit_server(reason: str) -> None:
    log("%s，服务退出" % reason)
    try:
        close_effect_window()
    except Exception:
        pass
    try:
        if os.path.isfile(SERVER_FILE):
            os.remove(SERVER_FILE)
    except OSError:
        pass
    os._exit(0)


def _watchdog(timeout: float = 600.0) -> None:
    """兜底：窗口被强杀（收不到 pagehide）时，长时间没有心跳就自行退出。"""
    while True:
        time.sleep(30)
        if not AUTO_CLOSE or not _seen_ping:
            continue
        if time.time() - _last_ping > timeout:
            _quit_server("已 %d 秒没有收到播放器窗口的心跳" % int(timeout))


# --------------------------------------------------------------------------
# 启动
# --------------------------------------------------------------------------


def free_port(preferred: int = 0) -> int:
    if preferred:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", preferred))
                return preferred
            except OSError:
                pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def find_browser() -> tuple[str, str] | None:
    """返回 (exe, 类型)。优先 Chrome，其次 Edge。"""
    candidates = [
        (os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                      r"Google\Chrome\Application\chrome.exe"), "chrome"),
        (os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                      r"Google\Chrome\Application\chrome.exe"), "chrome"),
        (os.path.join(os.environ.get("LOCALAPPDATA", ""),
                      r"Google\Chrome\Application\chrome.exe"), "chrome"),
        (os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                      r"Microsoft\Edge\Application\msedge.exe"), "edge"),
        (os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                      r"Microsoft\Edge\Application\msedge.exe"), "edge"),
    ]
    for path, kind in candidates:
        if path and os.path.isfile(path):
            return path, kind
    return None


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


# 启动时顺手清掉的纯缓存目录（本地可再生成，不需要联网重下）
TRIM_TARGETS = (
    "Default/Cache", "Default/Code Cache", "GPUPersistentCache", "GrShaderCache",
    "ShaderCache", "BrowserMetrics", "Default/GPUCache",
    "Default/DawnGraphiteCache", "Default/DawnWebGPUCache", "Subresource Filter",
    "CrashpadMetrics.pma", "CrashpadMetrics-active.pma",
)


def _profile_in_use(profile: str) -> bool:
    """Chrome 正开着这个 profile 时不要动它的缓存文件 —— 删正在用的缓存会把 profile 弄坏
    （表现为窗口打不开 / 报 incorrect profile type）。

    判断分两步：先看有没有 lockfile（Chrome 运行时才建），有再去问一次进程命令行
    里是不是真带着这个 profile —— 强杀 Chrome 会留下过期锁文件，只看文件会把清理永久废掉。
    """
    if os.name != "nt":
        return False
    if not os.path.exists(os.path.join(profile, "lockfile")):
        return False
    try:
        script = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
                  "Select-Object -ExpandProperty CommandLine")
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout or ""
    except Exception:
        return True                      # 查不出来就当作在用，宁可这次不清
    needle = os.path.realpath(profile).lower()
    return needle in out.lower()


def trim_browser_profile(profile: str, max_mb: float = 40.0) -> float:
    """Chrome 的磁盘缓存淘汰是懒执行的，会不知不觉涨到上百 MB。

    视频/预览图都来自本机服务，这些缓存纯属重复写盘 —— 启动前超过阈值就清掉。
    返回回收的 MB。
    """
    if not os.path.isdir(profile):
        return 0.0
    if _profile_in_use(profile):
        log("浏览器正在使用该 profile，跳过本次缓存清理")
        return 0.0
    root = os.path.realpath(profile)
    victims = []
    total = 0
    for rel in TRIM_TARGETS:
        path = os.path.join(profile, *rel.split("/"))
        if not os.path.exists(path):
            continue
        size = os.path.getsize(path) if os.path.isfile(path) else _dir_size(path)
        if size <= 0:
            continue
        total += size
        victims.append((path, size))
    if total < max_mb * 1024 * 1024:
        return 0.0
    freed = 0
    for path, size in victims:
        real = os.path.realpath(path)
        if not real.startswith(root + os.sep):     # 只删 profile 内的东西
            continue
        try:
            if os.path.isdir(real):
                shutil.rmtree(real, ignore_errors=True)
            else:
                os.remove(real)
            if not os.path.exists(real):
                freed += size
        except OSError:
            pass
    if freed:
        log("已清理浏览器缓存 %.1f MB（超过 %.0f MB 阈值）" % (freed / 1048576.0, max_mb))
    return freed / 1048576.0


def open_app_window(url: str) -> bool:
    """用 Chrome/Edge 的应用窗口模式打开（无地址栏，接近原生应用）。"""
    found = find_browser()
    if not found:
        return False
    exe, _kind = found
    profile = os.path.join(DATA_DIR, "browser-profile")
    try:
        trim_browser_profile(profile)
    except Exception as exc:
        log("清理缓存失败（忽略）: %s" % exc)
    args = [
        exe,
        "--app=" + url,
        "--user-data-dir=" + profile,
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,MediaRouter",
        "--autoplay-policy=no-user-gesture-required",
        "--window-size=1520,960",
        # 播放器的视频/预览都来自 127.0.0.1 本地服务，Chrome 的磁盘缓存纯属重复写盘。
        # 这里给个上限，再加上启动时的 trim_browser_profile() 兜底（淘汰是懒执行的，会超标）。
        "--disk-cache-size=33554432",
        "--media-cache-size=16777216",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        "--allow-file-access-from-files",
    ]
    try:
        subprocess.Popen(args, close_fds=True)
        return True
    except OSError as exc:
        log("启动浏览器窗口失败: %s" % exc)
        return False


def already_running() -> str | None:
    info = load_json(SERVER_FILE, None)
    if not isinstance(info, dict):
        return None
    port = info.get("port")
    url = info.get("url")
    if not port or not url:
        return None
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % port, timeout=1.5) as resp:
            if resp.status == 200:
                return url
    except Exception:
        return None
    return None


_stats: dict = {}


def main() -> int:
    global _stats, AUTO_CLOSE
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--port", type=int, default=0, help="指定端口（默认自动选择空闲端口）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开窗口")
    parser.add_argument("--rescan", action="store_true", help="忽略缓存重新探测")
    parser.add_argument("--browser", action="store_true", help="用默认浏览器标签页打开（不用应用窗口）")
    parser.add_argument("--keep-alive", action="store_true", help="窗口关闭后服务继续运行（调试用）")
    parser.add_argument("--dev", action="store_true", help="开发模式：允许 /api/library?data=worst 等最坏数据夹具")
    args = parser.parse_args()
    # 环境变量兜底：打包后的 exe 启动器没法传参，也给排障和自动化留个口子
    if os.environ.get("WE_PLAYER_NO_BROWSER"):
        args.no_browser = True
    if not args.port:
        try:
            args.port = int(os.environ.get("WE_PLAYER_PORT") or 0)
        except ValueError:
            args.port = 0
    if args.keep_alive:
        AUTO_CLOSE = False
    if args.dev:
        globals()["DEV_MODE"] = True

    ensure_dirs()
    load_state()

    running = already_running()
    if running and not args.port:
        log("检测到已在运行，直接打开窗口：%s" % running)
        if not args.no_browser:
            if not (args.browser and webbrowser.open(running)) and not open_app_window(running):
                webbrowser.open(running)
        return 0

    _stats = scan_library(force=args.rescan)

    port = free_port(args.port)
    url = "http://127.0.0.1:%d/" % port
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    save_json(SERVER_FILE, {"port": port, "url": url, "pid": os.getpid(), "started": time.time()})
    log("%s 已启动：%s" % (APP_NAME, url))

    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True)
    thread.start()
    threading.Thread(target=_watchdog, daemon=True).start()

    if not args.no_browser:
        if not (args.browser and webbrowser.open(url)) and not open_app_window(url):
            webbrowser.open(url)

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        log("收到 Ctrl+C，退出")
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            close_effect_window()
        except Exception:
            pass
        try:
            if os.path.isfile(SERVER_FILE):
                os.remove(SERVER_FILE)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # 保证异常写进日志
        import traceback
        log("致命错误: %s\n%s" % (exc, traceback.format_exc()))
        raise
