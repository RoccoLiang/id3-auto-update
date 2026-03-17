#!/usr/bin/env python3
"""
ID3 Auto Update - 自動從網路獲取正確音樂標籤並更新音樂檔案
支援格式：MP3、AIFF、WAV、FLAC、OGG、Opus、M4A、WMA
使用 AcoustID 音訊指紋識別歌曲，再從 MusicBrainz 取得完整 metadata
"""

import os
import re
import sys
import time
import argparse
from collections import Counter
import requests
import acoustid
import musicbrainzngs
from pathlib import Path
from dotenv import load_dotenv
from mutagen import File as MutagenFile

load_dotenv()
from mutagen.id3 import (
    ID3, ID3NoHeaderError,
    TIT2, TPE1, TALB, TDRC, TRCK, TCON, APIC
)
from mutagen.flac import FLAC, Picture
from mutagen.aiff import AIFF
from mutagen.wave import WAVE
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus
from mutagen.mp4 import MP4, MP4Cover
from mutagen.asf import ASF, ASFByteArrayAttribute

# ── 設定 ────────────────────────────────────────────────────────────────────
ACOUSTID_API_KEY = os.getenv("ACOUSTID_API_KEY", "")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "")
APP_NAME = "ID3-Auto-Update"
APP_VERSION = "1.0"

def _check_env():
    if not ACOUSTID_API_KEY:
        print("錯誤：請在 .env 填入 ACOUSTID_API_KEY")
        sys.exit(1)
    if not CONTACT_EMAIL:
        print("錯誤：請在 .env 填入 CONTACT_EMAIL")
        sys.exit(1)
    musicbrainzngs.set_useragent(APP_NAME, APP_VERSION, CONTACT_EMAIL)
# ────────────────────────────────────────────────────────────────────────────


def fingerprint_file(filepath: str) -> tuple[str, int] | None:
    """產生音訊指紋，回傳 (fingerprint, duration)"""
    try:
        duration, fp = acoustid.fingerprint_file(filepath)
        return fp.decode() if isinstance(fp, bytes) else fp, int(duration)
    except Exception as e:
        print(f"  [錯誤] 無法產生指紋：{e}")
        return None


def lookup_acoustid(fingerprint: str, duration: int) -> str | None:
    """用指紋查詢 AcoustID，回傳 MusicBrainz Recording ID"""
    try:
        results = acoustid.lookup(
            ACOUSTID_API_KEY,
            fingerprint,
            duration,
            meta="recordings releasegroups"
        )
        for score, recording_id, title, artist in acoustid.parse_lookup_result(results):
            if score > 0.5 and recording_id:
                print(f"  [指紋] 識別成功（信心：{score:.0%}）：{artist} - {title}")
                return recording_id
    except acoustid.WebServiceError as e:
        msg = str(e)
        if "invalid API key" in msg or "code 4" in msg:
            print(f"  [錯誤] AcoustID API Key 無效，請至 https://acoustid.org/new-application 申請")
        else:
            print(f"  [錯誤] AcoustID 查詢失敗：{e}")
    except Exception as e:
        print(f"  [錯誤] 解析結果失敗：{e}")
    return None


# 從 .env 讀取需要首字母大寫的詞彙（逗號分隔），排序確保 regex 穩定
_CAPITALIZE_WORDS = sorted(
    w.strip().lower()
    for w in os.getenv("CAPITALIZE_WORDS", "").split(",")
    if w.strip()
)
_CAPITALIZE_PATTERN = (
    re.compile(r'\b(' + '|'.join(re.escape(w) for w in _CAPITALIZE_WORDS) + r')\b', re.IGNORECASE)
    if _CAPITALIZE_WORDS else None
)

def normalize_title(title: str) -> str:
    """將特定詞彙（remix / mix 等）統一首字母大寫"""
    if not _CAPITALIZE_PATTERN:
        return title
    return _CAPITALIZE_PATTERN.sub(lambda m: m.group(0).capitalize(), title)


def get_metadata_from_mb(recording_id: str) -> dict | None:
    """從 MusicBrainz 取得完整 metadata"""
    try:
        result = musicbrainzngs.get_recording_by_id(
            recording_id,
            includes=["artists", "releases", "tags"]
        )
        rec = result["recording"]

        # 藝人
        artist = rec.get("artist-credit-phrase", "")

        # 標題
        title = normalize_title(rec.get("title", ""))

        # 專輯、年份、曲目 - 取第一個 release
        album, year, track_no, release_id = "", "", "", ""
        releases = rec.get("release-list", [])
        if releases:
            rel = releases[0]
            album = rel.get("title", "")
            year = rel.get("date", "")[:4]
            if year and not year.isdigit():
                year = ""
            release_id = rel.get("id", "")
            # 曲目編號
            medium_list = rel.get("medium-list", [])
            if medium_list:
                track_list = medium_list[0].get("track-list", [])
                if track_list:
                    track_no = track_list[0].get("number", "")

        # 曲風（從 tag-list 取）
        genre = ""
        tags = rec.get("tag-list", [])
        if tags:
            genre = tags[0].get("name", "").title()

        return {
            "title":      title,
            "artist":     artist,
            "album":      album,
            "year":       year,
            "track":      track_no,
            "genre":      genre,
            "release_id": release_id,
            "cover_url":  "",
        }

    except musicbrainzngs.WebServiceError as e:
        print(f"  [錯誤] MusicBrainz 查詢失敗：{e}")
    except Exception as e:
        print(f"  [錯誤] 解析 MusicBrainz 資料失敗：{e}")
    return None


def read_existing_tags(filepath: str) -> dict:
    """從現有標籤或檔名提取 title / artist 作為搜尋用"""
    title, artist = "", ""

    # ① 嘗試讀現有標籤
    try:
        audio = MutagenFile(filepath, easy=True)
        if audio and audio.tags:
            title  = (audio.tags.get("title")  or [""])[0]
            artist = (audio.tags.get("artist") or [""])[0]
    except Exception:
        pass

    # ② 從檔名解析（如果標籤沒有 title）
    if not title:
        stem = Path(filepath).stem
        stem = re.sub(r"^\d+[.\s\-]+", "", stem).strip()   # 去掉開頭 "01." / "01 - "
        if " - " in stem:
            parts = stem.split(" - ", 1)
            if not artist:
                artist = parts[0].strip()
            title = parts[1].strip()
        else:
            title = stem

    # ③ 從資料夾名稱猜 artist（如果還是空的）
    if not artist:
        folder = Path(filepath).parent.name
        if " - " in folder:
            artist = folder.split(" - ")[0].strip()
        else:
            artist = folder

    return {"title": title, "artist": artist}


def search_by_metadata(filepath: str) -> str | None:
    """備用識別：用現有標籤 / 檔名搜尋 MusicBrainz，回傳 Recording ID"""
    info = read_existing_tags(filepath)
    title  = info.get("title", "")
    artist = info.get("artist", "")

    if not title:
        return None

    print(f"  [備用] 文字搜尋：artist={artist!r}  title={title!r}")
    try:
        time.sleep(1)  # MusicBrainz 限速
        kwargs = {"recording": title, "limit": 5}
        if artist:
            kwargs["artist"] = artist
        results = musicbrainzngs.search_recordings(**kwargs)
        recordings = results.get("recording-list", [])
        for rec in recordings:
            score = int(rec.get("ext:score", 0))
            if score >= 70:
                rid = rec["id"]
                found_artist = rec.get("artist-credit-phrase", "")
                found_title  = rec.get("title", "")
                print(f"  [備用] 找到（信心：{score}%）：{found_artist} - {found_title}")
                return rid
        print("  [備用] 未找到信心足夠的結果（>= 70%），跳過")
    except Exception as e:
        print(f"  [備用] 搜尋失敗：{e}")
    return None


def fetch_cover_art(release_id: str) -> bytes | None:
    """從 Cover Art Archive 下載封面圖（MusicBrainz release ID）"""
    if not release_id:
        return None
    url = f"https://coverartarchive.org/release/{release_id}/front-500"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            print(f"  [封面] 下載成功 ({len(resp.content) // 1024} KB)")
            return resp.content
    except Exception as e:
        print(f"  [警告] 封面下載失敗：{e}")
    return None


def fetch_cover_from_url(url: str) -> bytes | None:
    """從直接 URL 下載封面圖（iTunes / Last.fm / Discogs）"""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            print(f"  [封面] 下載成功 ({len(resp.content) // 1024} KB)")
            return resp.content
    except Exception as e:
        print(f"  [警告] 封面下載失敗：{e}")
    return None


def search_itunes(title: str, artist: str) -> dict | None:
    """用 iTunes Search API 搜尋（免費，無需 Key）"""
    if not title:
        return None
    query = f"{artist} {title}".strip()
    print(f"  [iTunes] 搜尋：{query!r}")
    try:
        resp = requests.get(
            "https://itunes.apple.com/search",
            params={"term": query, "media": "music", "entity": "song", "limit": 5},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            print("  [iTunes] 無結果")
            return None
        r = results[0]
        print(f"  [iTunes] 找到：{r.get('artistName')} - {r.get('trackName')}")
        # 封面圖：把 100x100 換成 600x600 高解析
        cover_url = r.get("artworkUrl100", "").replace("100x100bb", "600x600bb")
        year = (r.get("releaseDate") or "")[:4]
        return {
            "title":      normalize_title(r.get("trackName", "")),
            "artist":     r.get("artistName", ""),
            "album":      r.get("collectionName", ""),
            "year":       year if year.isdigit() else "",
            "track":      str(r.get("trackNumber", "")),
            "genre":      r.get("primaryGenreName", ""),
            "release_id": "",
            "cover_url":  cover_url,
        }
    except Exception as e:
        print(f"  [iTunes] 搜尋失敗：{e}")
    return None


def search_lastfm(title: str, artist: str) -> dict | None:
    """用 Last.fm API 搜尋 track.getInfo"""
    api_key = os.getenv("LASTFM_API_KEY", "")
    if not api_key or not title or not artist:
        return None
    print(f"  [Last.fm] 搜尋：{artist!r} - {title!r}")
    try:
        resp = requests.get(
            "https://ws.audioscrobbler.com/2.0/",
            params={
                "method":   "track.getInfo",
                "api_key":  api_key,
                "artist":   artist,
                "track":    title,
                "format":   "json",
                "autocorrect": 1,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data or "track" not in data:
            print(f"  [Last.fm] 無結果")
            return None
        t = data["track"]
        album_data = t.get("album", {})
        # 封面：取最大尺寸
        images = album_data.get("image", [])
        cover_url = next((img["#text"] for img in reversed(images) if img.get("#text")), "")
        # 曲風：top tag
        tags = t.get("toptags", {}).get("tag", [])
        genre = tags[0]["name"].title() if tags else ""
        found_artist = t.get("artist", {}).get("name", artist) if isinstance(t.get("artist"), dict) else t.get("artist", artist)
        print(f"  [Last.fm] 找到：{found_artist} - {t.get('name')}")
        return {
            "title":      normalize_title(t.get("name", "")),
            "artist":     found_artist,
            "album":      album_data.get("title", ""),
            "year":       "",   # track.getInfo 不回傳年份，需另查
            "track":      str(t.get("@attr", {}).get("position", "")),
            "genre":      genre,
            "release_id": "",
            "cover_url":  cover_url,
        }
    except Exception as e:
        print(f"  [Last.fm] 搜尋失敗：{e}")
    return None


def search_discogs(title: str, artist: str) -> dict | None:
    """用 Discogs API 搜尋 release 資訊"""
    token = os.getenv("DISCOGS_TOKEN", "")
    if not token or not title:
        return None
    query = f"{artist} {title}".strip()
    print(f"  [Discogs] 搜尋：{query!r}")
    try:
        resp = requests.get(
            "https://api.discogs.com/database/search",
            params={"q": query, "type": "release", "per_page": 5},
            headers={
                "Authorization": f"Discogs token={token}",
                "User-Agent": f"{APP_NAME}/{APP_VERSION}",
            },
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            print("  [Discogs] 無結果")
            return None
        r = results[0]
        # title 格式通常是 "Artist - Album"
        raw_title = r.get("title", "")
        album = raw_title.split(" - ", 1)[-1] if " - " in raw_title else raw_title
        genres = r.get("genre", []) + r.get("style", [])
        year = str(r.get("year", ""))
        cover_url = r.get("cover_image", "") or r.get("thumb", "")
        print(f"  [Discogs] 找到：{raw_title} ({year})")
        return {
            "title":      normalize_title(title),   # Discogs 無 track title，沿用搜尋用的 title
            "artist":     artist,
            "album":      album,
            "year":       year if year.isdigit() else "",
            "track":      "",
            "genre":      genres[0].title() if genres else "",
            "release_id": "",
            "cover_url":  cover_url,
        }
    except Exception as e:
        print(f"  [Discogs] 搜尋失敗：{e}")
    return None


# ── 格式分組 ─────────────────────────────────────────────────────────────────
ID3_FORMATS     = {".mp3", ".aiff", ".aif", ".wav"}
VORBIS_FORMATS  = {".flac", ".ogg", ".opus"}
MP4_FORMATS     = {".m4a", ".m4b", ".aac"}
ASF_FORMATS     = {".wma"}
SUPPORTED_FORMATS = ID3_FORMATS | VORBIS_FORMATS | MP4_FORMATS | ASF_FORMATS
# ─────────────────────────────────────────────────────────────────────────────


def _print_preview(metadata: dict, cover: bytes | None):
    print("  [預覽模式] 不會實際修改檔案")
    print(f"    標題：{metadata.get('title')}")
    print(f"    藝人：{metadata.get('artist')}")
    print(f"    專輯：{metadata.get('album')}")
    print(f"    年份：{metadata.get('year')}")
    print(f"    曲目：{metadata.get('track')}")
    print(f"    曲風：{metadata.get('genre')}")
    print(f"    封面：{'有' if cover else '無'}")


def _apply_id3_frames(tags, metadata: dict, cover: bytes | None):
    """將欄位寫入 ID3 tags 物件（共用於 MP3 / AIFF / WAV）"""
    if metadata.get("title"):
        tags["TIT2"] = TIT2(encoding=3, text=metadata["title"])
    if metadata.get("artist"):
        tags["TPE1"] = TPE1(encoding=3, text=metadata["artist"])
    if metadata.get("album"):
        tags["TALB"] = TALB(encoding=3, text=metadata["album"])
    if metadata.get("year"):
        tags["TDRC"] = TDRC(encoding=3, text=metadata["year"])
    if metadata.get("track"):
        tags["TRCK"] = TRCK(encoding=3, text=str(metadata["track"]))
    if metadata.get("genre"):
        tags["TCON"] = TCON(encoding=3, text=metadata["genre"])
    if cover:
        tags["APIC"] = APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover)


def _apply_vorbis_tags(audio, metadata: dict, cover: bytes | None):
    """將欄位寫入 Vorbis Comment（共用於 FLAC / OGG / Opus）"""
    if metadata.get("title"):
        audio["title"] = metadata["title"]
    if metadata.get("artist"):
        audio["artist"] = metadata["artist"]
    if metadata.get("album"):
        audio["album"] = metadata["album"]
    if metadata.get("year"):
        audio["date"] = metadata["year"]
    if metadata.get("track"):
        audio["tracknumber"] = str(metadata["track"])
    if metadata.get("genre"):
        audio["genre"] = metadata["genre"]


def update_tags(filepath: str, metadata: dict, cover: bytes | None, dry_run: bool = False):
    """根據副檔名選擇正確的寫入方式"""
    if dry_run:
        _print_preview(metadata, cover)
        return

    ext = Path(filepath).suffix.lower()
    try:
        # ── ID3 系列：MP3 ──────────────────────────────────────────────────
        if ext == ".mp3":
            try:
                tags = ID3(filepath)
            except ID3NoHeaderError:
                tags = ID3()
            _apply_id3_frames(tags, metadata, cover)
            tags.save(filepath)

        # ── ID3 系列：AIFF ─────────────────────────────────────────────────
        elif ext in {".aiff", ".aif"}:
            audio = AIFF(filepath)
            if audio.tags is None:
                audio.add_tags()
            _apply_id3_frames(audio.tags, metadata, cover)
            audio.save()

        # ── ID3 系列：WAV ──────────────────────────────────────────────────
        elif ext == ".wav":
            audio = WAVE(filepath)
            if audio.tags is None:
                audio.add_tags()
            _apply_id3_frames(audio.tags, metadata, cover)
            audio.save()

        # ── Vorbis 系列：FLAC ──────────────────────────────────────────────
        elif ext == ".flac":
            audio = FLAC(filepath)
            _apply_vorbis_tags(audio, metadata, cover)
            if cover:
                pic = Picture()
                pic.type, pic.mime, pic.desc, pic.data = 3, "image/jpeg", "Cover", cover
                audio.clear_pictures()
                audio.add_picture(pic)
            audio.save()

        # ── Vorbis 系列：OGG / Opus ────────────────────────────────────────
        elif ext == ".ogg":
            audio = OggVorbis(filepath)
            _apply_vorbis_tags(audio, metadata, cover)
            audio.save()

        elif ext == ".opus":
            audio = OggOpus(filepath)
            _apply_vorbis_tags(audio, metadata, cover)
            audio.save()

        # ── MP4 系列：M4A / M4B / AAC ─────────────────────────────────────
        elif ext in {".m4a", ".m4b", ".aac"}:
            audio = MP4(filepath)
            if metadata.get("title"):
                audio["\xa9nam"] = [metadata["title"]]
            if metadata.get("artist"):
                audio["\xa9ART"] = [metadata["artist"]]
            if metadata.get("album"):
                audio["\xa9alb"] = [metadata["album"]]
            if metadata.get("year"):
                audio["\xa9day"] = [metadata["year"]]
            if metadata.get("track"):
                try:
                    track_num = int(str(metadata["track"]).split("/")[0])
                    audio["trkn"] = [(track_num, 0)]
                except (ValueError, IndexError):
                    pass
            if metadata.get("genre"):
                audio["\xa9gen"] = [metadata["genre"]]
            if cover:
                audio["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()

        # ── ASF 系列：WMA ──────────────────────────────────────────────────
        elif ext == ".wma":
            audio = ASF(filepath)
            if metadata.get("title"):
                audio["Title"] = [metadata["title"]]
            if metadata.get("artist"):
                audio["Author"] = [metadata["artist"]]
            if metadata.get("album"):
                audio["WM/AlbumTitle"] = [metadata["album"]]
            if metadata.get("year"):
                audio["WM/Year"] = [metadata["year"]]
            if metadata.get("track"):
                audio["WM/TrackNumber"] = [str(metadata["track"])]
            if metadata.get("genre"):
                audio["WM/Genre"] = [metadata["genre"]]
            if cover:
                # WM/Picture ASF 格式：type(1) + data_len(4) + mime(UTF-16LE null結尾) + desc(UTF-16LE null結尾) + data
                mime_utf16 = "image/jpeg".encode("utf-16-le") + b"\x00\x00"
                desc_utf16 = b"\x00\x00"  # 空描述
                pic_data = (
                    b"\x03"                              # type = front cover
                    + len(cover).to_bytes(4, "little")   # 圖片資料長度
                    + mime_utf16
                    + desc_utf16
                    + cover
                )
                audio["WM/Picture"] = [ASFByteArrayAttribute(pic_data)]
            audio.save()

        print("  [完成] 標籤已更新")
    except Exception as e:
        print(f"  [錯誤] 寫入標籤失敗：{e}")


def identify_file(filepath: str) -> dict | None:
    """
    識別單一檔案，回傳 metadata（不寫入）。
    識別鏈：① AcoustID → ② MusicBrainz 文字 → ③ iTunes → ④ Last.fm → ⑤ Discogs
    """
    p = Path(filepath)
    print(f"\n識別：{p.name}")

    result = fingerprint_file(filepath)
    if not result:
        return None
    fingerprint, duration = result

    # ① AcoustID 指紋 → MusicBrainz
    recording_id = lookup_acoustid(fingerprint, duration)

    # ② MusicBrainz 文字搜尋
    if not recording_id:
        recording_id = search_by_metadata(filepath)

    # ① ② 有結果 → 從 MusicBrainz 取完整 metadata
    if recording_id:
        time.sleep(1)  # MusicBrainz 限速
        metadata = get_metadata_from_mb(recording_id)
        if metadata:
            metadata.setdefault("cover_url", "")
            return metadata

    # ③ ④ ⑤ 備用 API：用現有標籤 / 檔名取得 title + artist
    info = read_existing_tags(filepath)
    title  = info.get("title", "")
    artist = info.get("artist", "")

    # ③ iTunes
    metadata = search_itunes(title, artist)
    if metadata:
        return metadata

    # ④ Last.fm
    time.sleep(0.5)
    metadata = search_lastfm(title, artist)
    if metadata:
        return metadata

    # ⑤ Discogs
    time.sleep(1)
    metadata = search_discogs(title, artist)
    if metadata:
        return metadata

    print("  [失敗] 所有方式都無法識別，跳過")
    return None


def vote_album_consensus(results: list[dict | None]) -> dict:
    """
    對所有成功識別的 metadata 進行投票，
    選出專輯級欄位（album / year / release_id）最多票的值。
    回傳 consensus dict，並印出投票報告。
    """

    successful = [m for m in results if m]
    total = len(results)
    found = len(successful)

    print(f"\n{'─'*50}")
    print(f"[投票] 識別成功：{found}/{total} 首")

    consensus: dict = {}
    for field, label in [
        ("album",      "專輯"),
        ("year",       "年份"),
        ("release_id", "Release ID"),
    ]:
        values = [m[field] for m in successful if m.get(field)]
        if not values:
            consensus[field] = ""
            continue
        winner, votes = Counter(values).most_common(1)[0]
        consensus[field] = winner
        print(f"[投票] {label}：「{winner}」  ({votes}/{found} 票)")

    print(f"{'─'*50}")
    return consensus


def process_folder(files: list[Path], dry_run: bool, no_cover: bool):
    """資料夾模式：先全部識別 → 投票 → 統一用 consensus 寫入"""

    # ── 第一輪：識別所有歌曲 ────────────────────────────────────────────────
    file_results: list[tuple[Path, dict | None]] = []
    for f in files:
        metadata = identify_file(str(f))
        file_results.append((f, metadata))

    # ── 投票 ────────────────────────────────────────────────────────────────
    all_meta = [m for _, m in file_results]
    consensus = vote_album_consensus(all_meta)

    # ── 下載封面（優先 consensus release_id，備用各曲 cover_url 多數決）──────
    cover = None
    if not no_cover:
        print()
        if consensus.get("release_id"):
            cover = fetch_cover_art(consensus["release_id"])
        if cover is None:
            # 從成功識別的結果中找最常出現的 cover_url
            cover_urls = [m["cover_url"] for m in all_meta if m and m.get("cover_url")]
            if cover_urls:
                best_url = Counter(cover_urls).most_common(1)[0][0]
                cover = fetch_cover_from_url(best_url)

    # ── 第二輪：寫入（per-track 欄位保留自身，專輯級欄位用 consensus）───────
    print(f"\n{'─'*50}")
    print("開始寫入標籤...")
    for f, metadata in file_results:
        print(f"\n寫入：{f.name}")
        if metadata is None:
            print("  [略過] 識別失敗")
            continue
        # 用 consensus 覆蓋專輯級欄位（artist 保留各曲目自身的值）
        for field in ("album", "year", "release_id"):
            if consensus.get(field):
                metadata[field] = consensus[field]
        update_tags(str(f), metadata, cover, dry_run=dry_run)


def _get_cover(metadata: dict, no_cover: bool) -> bytes | None:
    """根據 metadata 取得封面圖（優先 MusicBrainz，備用直接 URL）"""
    if no_cover:
        return None
    if metadata.get("release_id"):
        return fetch_cover_art(metadata["release_id"])
    if metadata.get("cover_url"):
        return fetch_cover_from_url(metadata["cover_url"])
    return None


def process_single(filepath: Path, dry_run: bool, no_cover: bool):
    """單一檔案模式：識別後直接寫入"""
    metadata = identify_file(str(filepath))
    if not metadata:
        return
    cover = _get_cover(metadata, no_cover)
    print()
    update_tags(str(filepath), metadata, cover, dry_run=dry_run)


def _ask(prompt: str, default: bool) -> bool:
    """是/否提問，回傳 bool"""
    hint = "[Y/n]" if default else "[y/N]"
    ans = input(f"{prompt} {hint}: ").strip().lower()
    if ans == "":
        return default
    return ans in {"y", "yes"}


def _ask_path(prompt: str) -> Path:
    """要求輸入路徑，直到存在為止"""
    while True:
        raw = input(prompt).strip().strip("'\"")
        p = Path(raw).expanduser()
        if p.exists():
            return p
        print(f"  找不到：{p}，請重新輸入")


def _collect_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    files = sorted(f for f in target.rglob("*") if f.suffix.lower() in SUPPORTED_FORMATS)
    if not files:
        print("找不到任何支援的音樂檔案（MP3 / AIFF / WAV / FLAC / OGG / Opus / M4A / WMA）")
        sys.exit(0)
    return files


def _run(mode: int, target: Path, dry_run: bool, no_cover: bool):
    files = _collect_files(target)

    if dry_run:
        print("（預覽模式：不會修改任何檔案）")

    if mode == 1:
        # 單曲模式：逐一識別並直接寫入，不投票
        print(f"找到 {len(files)} 個檔案，單曲模式")
        for f in files:
            process_single(f, dry_run=dry_run, no_cover=no_cover)
    else:
        # 專輯模式：先全部識別，投票後統一寫入
        print(f"找到 {len(files)} 個檔案，專輯模式（投票）")
        process_folder(files, dry_run=dry_run, no_cover=no_cover)

    print("\n全部完成！")


def _menu():
    """互動式選單"""
    print()
    print("╔══════════════════════════════════╗")
    print("║        ID3 Auto Update           ║")
    print("╠══════════════════════════════════╣")
    print("║  1.  單曲模式  直接識別並更新     ║")
    print("║  2.  專輯模式  投票後統一更新     ║")
    print("║  0.  離開                        ║")
    print("╚══════════════════════════════════╝")
    print()

    while True:
        choice = input("請選擇模式 [0/1/2]: ").strip()
        if choice in {"0", "1", "2"}:
            break
        print("  請輸入 0、1 或 2")

    if choice == "0":
        sys.exit(0)

    mode = int(choice)
    print()
    target = _ask_path("請輸入音樂檔案或資料夾路徑：")
    dry_run  = _ask("預覽模式（不修改檔案）？", default=False)
    no_cover = not _ask("下載封面圖？", default=True)
    print()

    _run(mode, target, dry_run, no_cover)


def main():
    parser = argparse.ArgumentParser(
        description="自動從網路獲取正確音樂標籤並更新音樂檔案",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
模式：
  1 = 單曲模式，直接識別並更新（不投票）
  2 = 專輯模式，先全部識別，投票後統一更新

範例：
  python3 id3_update.py                         # 互動選單
  python3 id3_update.py 1 song.mp3              # 單曲模式
  python3 id3_update.py 2 ./album/              # 專輯模式
  python3 id3_update.py 2 ./album/ --dry-run    # 預覽
  python3 id3_update.py 2 ./album/ --no-cover   # 不下載封面
        """
    )
    parser.add_argument("mode", nargs="?", choices=["1", "2"],
                        help="1=單曲模式  2=專輯模式（省略則進入選單）")
    parser.add_argument("path", nargs="?", help="音樂檔案或資料夾路徑")
    parser.add_argument("--dry-run", action="store_true", help="預覽模式，不修改檔案")
    parser.add_argument("--no-cover", action="store_true", help="不下載封面圖")
    args = parser.parse_args()

    _check_env()

    # 沒有帶參數 → 互動選單
    if not args.mode:
        _menu()
        return

    if not args.path:
        print("錯誤：請提供路徑")
        sys.exit(1)

    target = Path(args.path)
    if not target.exists():
        print(f"錯誤：找不到 {target}")
        sys.exit(1)

    _run(int(args.mode), target, dry_run=args.dry_run, no_cover=args.no_cover)


if __name__ == "__main__":
    main()
