# ID3 Auto Update

自動從網路獲取正確音樂資訊，並更新音樂檔案的 ID3 標籤。

使用 [AcoustID](https://acoustid.org/) 音訊指紋識別歌曲，再從 [MusicBrainz](https://musicbrainz.org/) 取得完整 metadata，封面圖片來自 [Cover Art Archive](https://coverartarchive.org/)。

## 支援格式

| 格式 | 副檔名 | 標籤系統 |
|------|--------|---------|
| MP3 | `.mp3` | ID3 |
| AIFF | `.aiff` `.aif` | ID3 |
| WAV | `.wav` | ID3 |
| FLAC | `.flac` | Vorbis Comment |
| OGG Vorbis | `.ogg` | Vorbis Comment |
| Opus | `.opus` | Vorbis Comment |
| M4A / AAC | `.m4a` `.m4b` `.aac` | MP4 |
| WMA | `.wma` | ASF |

## 安裝

### 1. 安裝 fpcalc（音訊指紋工具）

```bash
brew install chromaprint
```

### 2. 安裝 Python 套件

```bash
pip3 install -r requirements.txt
```

### 3. 設定 API Key

複製 `.env.example` 為 `.env`：

```bash
cp .env.example .env
```

編輯 `.env`，填入你的資訊：

```
ACOUSTID_API_KEY=你的Key      # 至 https://acoustid.org/new-application 免費申請
CONTACT_EMAIL=your@email.com  # MusicBrainz 要求提供聯絡方式
```

## 使用方式

```bash
# 更新單一檔案
python3 id3_update.py song.mp3

# 更新整個專輯資料夾（自動啟用投票機制）
python3 id3_update.py ./album/

# 預覽將會做的修改，不實際寫入
python3 id3_update.py ./album/ --dry-run

# 不下載封面圖
python3 id3_update.py ./album/ --no-cover
```

## 專輯投票機制

處理整個資料夾時，程式會：

1. 識別所有歌曲（音訊指紋 + 文字搜尋備用）
2. 對 **專輯名稱**、**年份**、**Release ID** 進行多數決投票
3. 用投票結果統一覆蓋，防止少數識別錯誤污染整張專輯標籤
4. **藝人**欄位保留各曲目自身的 MusicBrainz 資料（支援 feat. 等）

## 設定選項（.env）

| 變數 | 說明 |
|------|------|
| `ACOUSTID_API_KEY` | AcoustID API Key（必填）|
| `CONTACT_EMAIL` | 聯絡 Email，用於 MusicBrainz User-Agent（必填）|
| `CAPITALIZE_WORDS` | 標題中永遠首字母大寫的詞彙，逗號分隔（選填）|

## 識別流程

```
音樂檔案
  ↓
① 音訊指紋（fpcalc）→ AcoustID API
  ↓ 失敗時
② 現有標籤 / 檔名 → MusicBrainz 文字搜尋
  ↓
③ MusicBrainz API → 完整 metadata
  ↓
④ Cover Art Archive → 封面圖
  ↓
⑤ 寫入標籤
```
