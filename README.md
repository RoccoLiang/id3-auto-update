# ID3 Auto Update

你是不是常常遇到這種情況——音樂庫裡一堆歌曲標題亂掉、專輯封面空白、藝人名稱前後不一致？這個工具就是為了解決這個問題而生的。

它會自動幫你的音樂檔案從網路上找到正確的 metadata，同時比對 **5 個來源**的資訊，讓你親眼確認後再寫入，不會偷偷改掉你不想動的東西。

---

## 支援哪些格式

幾乎所有常見格式都能處理：

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

### 1. 安裝 fpcalc（負責聽歌辨曲的工具）

```bash
brew install chromaprint
```

### 2. 安裝 Python 套件

```bash
pip3 install -r requirements.txt
```

### 3. 設定 API Key

先把範本複製一份：

```bash
cp .env.example .env
```

再打開 `.env` 填入你的資訊。AcoustID 和 Email 是必填的，其他平台有填才會查：

```env
# 必填
ACOUSTID_API_KEY=你的Key       # 到 https://acoustid.org/new-application 免費申請
CONTACT_EMAIL=your@email.com   # MusicBrainz 規定要填聯絡方式，填你的 email 就好

# 選填——有填才會查詢這個平台
LASTFM_API_KEY=你的Key         # https://www.last.fm/api/account/create
DISCOGS_TOKEN=你的Token        # https://www.discogs.com/settings/developers

# 選填——這些詞在標題裡會永遠保持首字母大寫
CAPITALIZE_WORDS=remix,mix,extended,edit,radio,version,vocal,instrumental
```

---

## 怎麼用

### 最簡單的方式：直接跑，跟著選單走

```bash
python3 id3_update.py
```

程式會問你要用哪個模式、要處理哪個檔案或資料夾，一步一步帶你完成。

### 也可以直接下指令

```bash
# 單曲模式，處理一首歌
python3 id3_update.py 1 song.mp3

# 專輯模式，處理整個資料夾
python3 id3_update.py 2 ./album/

# 先預覽要改什麼，不實際寫入
python3 id3_update.py 2 ./album/ --dry-run

# 不要下載封面圖
python3 id3_update.py 2 ./album/ --no-cover

# 專輯模式 + 幫你重新命名檔案 + 順便產生播放清單
python3 id3_update.py 2 ./album/ --rename --m3u8
```

---

## 兩種模式

### 模式 1：單曲模式

一次處理一首，適合你有特定幾首想確認的歌。

程式跑完後會把各平台找到的結果並排列出來，你自己決定要用哪個：

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
```

選好之後會再顯示完整的標籤內容讓你確認：

```
  標題：Dynamite (Extended Mix)
  藝人：Gareth Emery feat. Christina Novelli
  專輯：Dynamite
  年份：2014
  曲目：1
  曲風：Trance
  封面：有 ✓
  請選擇 [A/E/S/K]（Enter = A）：
```

| 按鍵 | 做什麼 |
|------|--------|
| `A` / Enter | 確認，寫入標籤 |
| `E` | 手動修改某幾個欄位 |
| `S` | 覺得不對？重新輸入關鍵字搜尋 |
| `K` | 這首跳過，處理下一首 |

一首處理完，程式會直接問你要不要繼續下一首，不用重新啟動。

### 模式 2：專輯模式

整個資料夾一起跑，適合整張專輯要批次更新的情況。

這個模式有個「**投票機制**」——每首歌識別完後，程式會統計哪個專輯名稱、年份、Release ID 出現最多次，用多數決的結果統一套用，避免個別歌曲識別失誤拉垮整張專輯的標籤。

- **藝人**欄位不參與投票，每首保留各自的識別結果（這樣 feat. 才不會被蓋掉）
- 可以順便把檔案重新命名成 `01. Title.ext` 的格式
- 可以自動產生 `Artist - Album.m3u8` 播放清單

---

## 識別來源說明

```
音樂檔案
  │
  ├─① 音訊指紋（fpcalc）→ AcoustID → MusicBrainz
  │     用「聽」的方式辨認這首歌，準確度最高
  │
  ├─② 現有標籤 / 檔名 → MusicBrainz 文字搜尋
  │     指紋失敗時，改用現有的標題藝人名稱去搜
  │
  ├─③ iTunes Search API（免費，無需 Key）
  │
  ├─④ Last.fm track.getInfo
  │     預設優先採用，資料通常比較乾淨
  │
  └─⑤ Discogs 資料庫搜尋
         ↓
     封面圖下載（Cover Art Archive → iTunes → 各平台回傳圖片）
         ↓
     寫入標籤
```

**單曲模式**：5 個來源全部同時查，結果並排讓你挑。

**專輯模式**：依序試，找到結果就停（速度優先，不需要你一首一首確認）。

---

## .env 設定一覽

| 變數 | 必填 | 說明 |
|------|:----:|------|
| `ACOUSTID_API_KEY` | ✅ | AcoustID 音訊指紋 API Key |
| `CONTACT_EMAIL` | ✅ | MusicBrainz 要求的聯絡信箱 |
| `LASTFM_API_KEY` | — | Last.fm API Key，沒填就跳過 Last.fm |
| `DISCOGS_TOKEN` | — | Discogs Personal Access Token，沒填就跳過 Discogs |
| `CAPITALIZE_WORDS` | — | 標題裡要保持首字母大寫的詞，逗號分隔 |
