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
**壓縮流程：** 讀取原始 Bytes → 統計頻率 → 使用 Min-Heap 建立 Huffman Tree → 取得碼長 → 產生 Canonical Huffman 編碼 → Bit Packing → 寫入 HUF1 檔頭、碼表與壓縮資料。

**解壓縮流程：** 解析 HUF1 檔頭 → 讀取碼長 → 重建 Canonical Huffman 編碼 → 逐位元解碼 → CRC32 檢查。

**RAW 模式：** 若壓縮後資料加上碼表沒有比原始資料小，程式會選擇直接儲存原始 Bytes；此時壓縮檔可能略大，仍可無失真還原。

**壓縮比：** 原始 Bytes ÷ 壓縮後 Bytes，例如 1.61 表示 **1.61:1**。

**空間節省率：** (1 − 壓縮後 Bytes ÷ 原始 Bytes) × 100%。

**注意：** CSV 的「執行時間」是記憶體中執行壓縮與解壓縮及驗證的合計時間，不包括瀏覽器上傳或下載時間；與原本 CLI 的檔案讀寫計時口徑略有不同。

**軟體架構：** `lossless_huffman.py` 為自行實作的壓縮引擎；`streamlit_app.py` 僅負責網頁操作、結果展示與下載。Streamlit 是介面套件，不是壓縮演算法。
""")
