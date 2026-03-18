# ID3 Auto Update

自動從網路獲取正確的音樂資訊，並更新音樂檔案的 ID3 標籤。

同時查詢 **5 個資料來源**（AcoustID、MusicBrainz、iTunes、Last.fm、Discogs），在互動式選單中並排比較結果，讓你選出最正確的資訊後再寫入。

---

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

---

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

```env
# 必填
ACOUSTID_API_KEY=你的Key       # https://acoustid.org/new-application 免費申請
CONTACT_EMAIL=your@email.com   # MusicBrainz User-Agent 必填

# 選填（有填才會查詢對應平台）
LASTFM_API_KEY=你的Key         # https://www.last.fm/api/account/create
DISCOGS_TOKEN=你的Token        # https://www.discogs.com/settings/developers

# 標題中永遠首字母大寫的詞彙（逗號分隔）
CAPITALIZE_WORDS=remix,mix,extended,edit,radio,version,vocal,instrumental
```

---

## 使用方式

### 互動選單（推薦）

```bash
python3 id3_update.py
```

啟動後選擇模式，程式會引導你完成所有步驟。

### 命令列模式

```bash
# 單曲模式
python3 id3_update.py 1 song.mp3

# 專輯模式
python3 id3_update.py 2 ./album/

# 預覽，不實際修改檔案
python3 id3_update.py 2 ./album/ --dry-run

# 不下載封面圖
python3 id3_update.py 2 ./album/ --no-cover

# 專輯模式 + 重新命名 + 建立播放清單
python3 id3_update.py 2 ./album/ --rename --m3u8
```

---

## 模式說明

### 模式 1：單曲模式

每次處理一首歌，完整流程如下：

1. **同時查詢所有資料來源**，並排顯示比較表
2. **選擇資料來源**（預設 Last.fm，直接按 Enter 採用）
3. **確認畫面**（預設接受，直接按 Enter 寫入）
4. 詢問是否繼續處理下一首（無需重啟程式）

```
識別結果比較：
  [1] AcoustID + MusicBrainz (97%)
       Gareth Emery feat. Christina Novelli - Dynamite (Extended Mix)  《Dynamite》  2014
  [2] iTunes
       Gareth Emery - Dynamite (Extended Mix)  《Garuda》  2014
  [3] Last.fm ★
       Gareth Emery - Dynamite (Extended Mix)
  [4] Discogs
       Gareth Emery - Dynamite (Extended Mix)  《Dynamite》  2014
  [0] 手動輸入
  請選擇資料來源 [1-4/0]（Enter = [3]）：

  標題：Dynamite (Extended Mix)
  藝人：Gareth Emery feat. Christina Novelli
  專輯：Dynamite
  年份：2014
  曲目：1
  曲風：Trance
  封面：有 ✓
  請選擇 [A/E/S/K]（Enter = A）：
```

確認畫面選項：

| 按鍵 | 動作 |
|------|------|
| `A` / Enter | 接受並寫入標籤 |
| `E` | 手動逐欄位編輯 |
| `S` | 重新輸入關鍵字搜尋 MusicBrainz |
| `K` | 跳過此檔案 |

### 模式 2：專輯模式

批次處理整個資料夾，使用**投票機制**確保整張專輯標籤一致：

1. 識別資料夾內所有歌曲
2. 對 **專輯名稱**、**年份**、**Release ID** 進行多數決投票
3. 用票數最高的結果統一覆蓋，避免少數識別錯誤污染整張專輯
4. **藝人**欄位保留各曲目自身的資料（正確支援 feat.）
5. 可選擇重新命名檔案（`XX. Title.ext`）及建立 M3U8 播放清單

---

## 識別流程

```
音樂檔案
  │
  ├─① 音訊指紋（fpcalc）→ AcoustID API
  │       ↓ 成功
  │   MusicBrainz Recording ID → 完整 metadata
  │
  ├─② 現有標籤 / 檔名 → MusicBrainz 文字搜尋
  │
  ├─③ iTunes Search API（免費，無需 Key）
  │
  ├─④ Last.fm track.getInfo
  │
  └─⑤ Discogs 資料庫搜尋
         ↓
     封面圖（Cover Art Archive → iTunes → 各 API 回傳 URL）
         ↓
     寫入標籤
```

單曲模式（1）：全部同時執行，結果並排供使用者選擇。
專輯模式（2）：依序嘗試，找到結果即停止（速度優先）。

---

## .env 設定一覽

| 變數 | 必填 | 說明 |
|------|------|------|
| `ACOUSTID_API_KEY` | 必填 | AcoustID 音訊指紋 API Key |
| `CONTACT_EMAIL` | 必填 | MusicBrainz User-Agent 聯絡信箱 |
| `LASTFM_API_KEY` | 選填 | Last.fm API Key，未填則跳過 Last.fm |
| `DISCOGS_TOKEN` | 選填 | Discogs Personal Access Token，未填則跳過 Discogs |
| `CAPITALIZE_WORDS` | 選填 | 標題中永遠首字母大寫的詞彙，逗號分隔 |
