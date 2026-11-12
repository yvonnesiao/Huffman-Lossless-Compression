"""Huffman 無失真壓縮 Streamlit UI。

保留 lossless_huffman.py 原有 Canonical Huffman 演算法，不使用第三方壓縮套件。
啟動：uv run --with streamlit --python 3.14 streamlit run streamlit_app.py
"""
from __future__ import annotations

import csv
import hashlib
import io
import time
import zipfile

import pandas as pd
import streamlit as st

from lossless_huffman import (
    HEADER,
    MAGIC,
    METHOD_HUFFMAN,
    compress_bytes,
    decompress_bytes,
)

st.set_page_config(page_title="Huffman 無失真壓縮工具", page_icon="🗜️", layout="wide")
st.title("🗜️ Huffman 無失真壓縮與解壓縮")
st.caption("自行實作 Canonical Huffman Coding · 支援多檔處理、壓縮比分析、CRC32 與 SHA-256 驗證")

# 把測試結果輸出成 Excel 也能正確顯示中文的 UTF-8 BOM CSV。
COLUMNS = ["檔案名稱", "原始大小(Bytes)", "壓縮後大小(Bytes)", "壓縮比", "空間節省率(%)", "執行時間(秒)", "無失真驗證", "儲存模式"]


def to_csv(rows: list[dict]) -> bytes:
    """將結果表轉成 UTF-8 BOM 編碼 CSV；Excel 可直接開啟中文欄名。"""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def inspect_mode(blob: bytes) -> str:
    """讀取自訂 HUF1 檔頭的壓縮模式。"""
    if len(blob) < HEADER.size or blob[:4] != MAGIC:
        return "未知"
    method = HEADER.unpack_from(blob)[1]
    return "Huffman" if method == METHOD_HUFFMAN else "RAW"


def analyze(filename: str, original: bytes) -> tuple[bytes, dict, bytes]:
    """壓縮並立即解壓縮，產生統計與無失真驗證結果。"""
    started = time.perf_counter()
    zipped = compress_bytes(original)
    restored = decompress_bytes(zipped)
    elapsed = time.perf_counter() - started
    size, packed_size = len(original), len(zipped)
    valid = original == restored and hashlib.sha256(original).digest() == hashlib.sha256(restored).digest()
    ratio = size / packed_size if packed_size else 0.0
    savings = (1 - packed_size / size) * 100 if size else 0.0
    row = {
        "檔案名稱": filename,
        "原始大小(Bytes)": size,
        "壓縮後大小(Bytes)": packed_size,
        "壓縮比": round(ratio, 4),
        "空間節省率(%)": round(savings, 2),
        "執行時間(秒)": round(elapsed, 4),
        "無失真驗證": "PASS" if valid else "FAIL",
        "儲存模式": inspect_mode(zipped),
    }
    return zipped, row, restored


def package_zip(items: list[tuple[str, bytes]]) -> bytes:
    """將多份壓縮檔組合成一個方便下載的 ZIP。ZIP 僅作封裝，不再次壓縮。"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as zf:
        # 相同名稱上傳多次時，使用序號避免 ZIP 內名稱衝突。
        seen = set()
        for name, data in items:
            base, unique = name, name
            suffix = 2
            while unique in seen:
                unique = f"{suffix}_{base}"
                suffix += 1
            seen.add(unique)
            zf.writestr(unique, data)
    return output.getvalue()


section = st.radio(
    "功能選擇",
    ["📦 壓縮與批次測試", "📂 解壓縮", "📘 原理與使用說明"],
    horizontal=True,
    label_visibility="collapsed",
    key="section_nav",
)

if section == "📦 壓縮與批次測試":
    st.subheader("上傳原始檔案")
    st.write("可一次選取 test1～test4，也可上傳其他類型的檔案。所有處理都以原始 Bytes 進行，不會改變文字編碼。")
    uploaded = st.file_uploader("選擇要壓縮的檔案（可多選）", accept_multiple_files=True, key="upload_original")

    if uploaded:
        # 以檔案名稱與內容雜湊作為快取識別，避免下載時重新壓縮。
        file_items = [(item.name, item.getvalue()) for item in uploaded]
        if st.button("開始壓縮、解壓驗證與統計", type="primary", use_container_width=True):
            results, zipped_items = [], []
            with st.spinner("正在執行 Huffman 編碼、解碼與驗證…"):
                for name, data in file_items:
                    try:
                        zipped, row, _ = analyze(name, data)
                        results.append(row)
                        zipped_items.append((name + ".huf", zipped))
                    except (ValueError, KeyError, OverflowError) as exc:
                        st.error(f"處理 {name} 失敗：{exc}")
            st.session_state["huffman_results"] = results
            st.session_state["huffman_zipped_items"] = zipped_items
            st.session_state["huffman_upload_signature"] = [(name, hashlib.sha256(data).hexdigest()) for name, data in file_items]

        signature = [(name, hashlib.sha256(data).hexdigest()) for name, data in file_items]
        if signature == st.session_state.get("huffman_upload_signature"):
            rows = st.session_state.get("huffman_results", [])
            zipped_items = st.session_state.get("huffman_zipped_items", [])
            if rows:
                st.divider()
                st.subheader("壓縮結果")
                total_original = sum(row["原始大小(Bytes)"] for row in rows)
                total_zipped = sum(row["壓縮後大小(Bytes)"] for row in rows)
                total_savings = (1 - total_zipped / total_original) * 100 if total_original else 0
                a, b, c, d = st.columns(4)
                a.metric("檔案數量", len(rows))
                b.metric("原始總大小", f"{total_original:,} B")
                c.metric("壓縮後總大小", f"{total_zipped:,} B")
                d.metric("總空間節省率", f"{total_savings:.2f}%")
                st.dataframe(rows, use_container_width=True, hide_index=True)
                if any(row["無失真驗證"] != "PASS" for row in rows):
                    st.error("有檔案未通過無失真驗證，請勿以此結果取代原始檔案。")
                else:
                    st.success("全部通過：壓縮後再解壓的內容與原始檔案完全一致（Bytes + SHA-256）。")

                st.bar_chart(pd.DataFrame(rows).set_index("檔案名稱")[["空間節省率(%)"]], y_label="空間節省率 (%)")
                st.download_button("⬇️ 下載測試結果 CSV", data=to_csv(rows), file_name="Huffman_壓縮測試結果.csv", mime="text/csv", use_container_width=True)
                if len(zipped_items) == 1:
                    name, blob = zipped_items[0]
                    st.download_button("⬇️ 下載 .huf 壓縮檔", data=blob, file_name=name, mime="application/octet-stream", use_container_width=True)
                elif zipped_items:
                    st.download_button("⬇️ 一次下載全部 .huf（ZIP 封裝）", data=package_zip(zipped_items), file_name="Huffman_壓縮檔案.zip", mime="application/zip", use_container_width=True)
    else:
        st.info("先選擇要壓縮的檔案。")

if section == "📂 解壓縮":
    st.subheader("還原 .huf 檔案")
    st.write("上傳本程式產生的 HUF1 格式 `.huf` 檔；解壓縮時自動驗證檔案內的 CRC32。")
    huf_upload = st.file_uploader("選擇 .huf 壓縮檔案", type=["huf"], key="upload_huf")
    if huf_upload is not None:
        compressed = huf_upload.getvalue()
        try:
            restored = decompress_bytes(compressed)
            st.success("解壓縮成功，CRC32 驗證通過。")
            x, y = st.columns(2)
            x.metric("壓縮檔大小", f"{len(compressed):,} B")
            y.metric("還原檔大小", f"{len(restored):,} B")
            base_name = huf_upload.name[:-4] if huf_upload.name.lower().endswith(".huf") else huf_upload.name
            st.download_button("⬇️ 下載還原檔案", data=restored, file_name=base_name + ".restored", mime="application/octet-stream", use_container_width=True)
        except (ValueError, KeyError, OverflowError) as exc:
            st.error(f"無法解壓縮：{exc}")
            st.warning("請確認檔案是此程式產生的 HUF1 格式，且內容沒有受損。")

if section == "📘 原理與使用說明":
    st.subheader("演算法簡介")
    st.markdown("""
## 演算法簡介

**1. 壓縮是怎麼運作的？**

程式會先讀取上傳的檔案，統計每個位元組（Byte）出現的次數。接著利用 Min-Heap（最小堆積）建立 Huffman Tree，讓出現頻率較高的資料使用較短的二進位編碼，減少整體需要的儲存空間。

完成編碼後，程式會利用 Canonical Huffman Coding 整理編碼表，再將資料打包成 Bytes，最後產生 `.huf` 壓縮檔案。

**2. 解壓縮是怎麼運作的？**

解壓縮時，程式會先讀取 `.huf` 檔案中的資訊，重新建立 Huffman 編碼表，再把壓縮資料逐一解碼，還原成原本的檔案內容。

還原完成後，程式會利用 CRC32 檢查資料是否正確，確保解壓縮過程沒有造成資料損壞。

**3. 為什麼有 RAW 模式？**

不是每個檔案都一定能壓縮得更小。

如果 Huffman 壓縮後的資料加上編碼表，反而比原始資料還大，程式就會切換成 RAW 模式，直接保存原始資料。

雖然這種情況不會減少檔案大小，但仍然可以完整還原資料。

**4. 壓縮比與空間節省率是什麼？**

壓縮比是用來比較原始檔案與壓縮後檔案的大小。

例如壓縮比為 **1.61:1**，代表原始檔案大小大約是壓縮檔案的 1.61 倍。

空間節省率則是用百分比來表示實際減少多少儲存空間。例如節省率為 **37.89%**，就代表壓縮後比原本少使用了 37.89% 的空間。

**5. 怎麼確認是無失真壓縮？**

程式在測試時，會將檔案壓縮後再解壓縮，並比較還原資料與原始資料是否完全相同。

除了直接比較資料內容，也會使用 SHA-256 進行驗證。如果兩項檢查都通過，就會顯示 `PASS`，代表檔案成功完整還原。

**6. 執行時間是怎麼計算的？**

程式會記錄從開始壓縮到完成解壓縮的總執行時間。

這項數據主要用來比較不同大小檔案的處理效率，不包含使用者上傳或下載檔案所花費的時間。

**7. 程式的架構**

整個專題主要分成兩個 Python 檔案：

- `lossless_huffman.py`：負責 Huffman 壓縮、解壓縮及資料驗證，是整個系統的核心。
- `streamlit_app.py`：負責網頁介面，讓使用者能夠上傳檔案、查看壓縮結果、比較壓縮比及下載檔案。

Streamlit 主要是讓程式操作起來更方便，真正的 Huffman 演算法仍然是使用 Python 自行實作。
""")
