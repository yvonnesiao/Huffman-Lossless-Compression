from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import heapq
from pathlib import Path
import struct
import time
import zlib
import csv

MAGIC=b"HUF1"
HEADER=struct.Struct(">4sBQI H")  # 魔術字、模式、原始長度、CRC32、符號數
METHOD_RAW=0
METHOD_HUFFMAN=1

#使用最小堆建立Huffman樹，回傳每個byte符號的碼長
def build_code_lengths(data:bytes)->dict[int,int]:
    frequency=Counter(data)
    if not frequency:
        return {}
    if len(frequency)==1:
        return {next(iter(frequency)): 1}

    #每個節點：(頻率、穩定排序序號、樹節點)；葉節點使用int，內節點使用tuple
    heap=[]
    serial=0
    for symbol,freq in sorted(frequency.items()):
        heapq.heappush(heap,(freq,serial,symbol))
        serial+=1

    while len(heap)>1:
        f1,_,left=heapq.heappop(heap)
        f2,_,right=heapq.heappop(heap)
        heapq.heappush(heap,(f1+f2,serial,(left,right)))
        serial+=1

    root=heap[0][2]
    lengths={}
    stack=[(root,0)]
    while stack:
        node,depth=stack.pop()
        if isinstance(node,int):
            lengths[node]=depth
        else:
            left,right=node
            stack.append((right,depth+1))
            stack.append((left,depth+1))
    return lengths

#根據碼長與符號排序，建立標準Huffman碼(值為碼字整數,位元長度)
def canonical_codes(lengths:dict[int,int])->dict[int,tuple[int,int]]:
    if any(not 1<=length<=255 for length in lengths.values()):
        raise ValueError("非法Huffman碼長")
    code=0
    previous_length=0
    codes={}
    for symbol,length in sorted(lengths.items(),key=lambda x: (x[1],x[0])):
        code<<=length-previous_length
        if code>=(1<<length):
            raise ValueError("Huffman碼表無效")
        codes[symbol]=(code,length)
        code+=1
        previous_length=length
    return codes

#將二進位編碼打包成Bytes
def encode_bits(data:bytes,codes:dict[int,tuple[int,int]])->bytes:
    output=bytearray()
    buffer=0
    bits=0
    for symbol in data:
        code,length=codes[symbol]
        buffer=(buffer<<length) | code
        bits+=length
        while bits>=8:
            bits-=8
            output.append((buffer>>bits) & 0xFF)
            buffer &= (1<<bits)-1
    if bits:
        output.append((buffer<<(8-bits)) & 0xFF)
    return bytes(output)

#逐位解讀Huffman碼並還原原始位元組
def decode_bits(payload:bytes,lengths:dict[int,int],original_size:int)->bytes:
    if original_size==0:
        if payload or lengths:
            raise ValueError("空檔案的壓縮內容不合法")
        return b""
    if not lengths:
        raise ValueError("缺少Huffman碼表")

    decode_map={(length,code):symbol for symbol,(code,length) in canonical_codes(lengths).items()}
    max_length=max(lengths.values())
    output=bytearray()
    code=0
    length=0
    for index,byte in enumerate(payload):
        for shift in range(7,-1,-1):
            code=(code<<1) | ((byte>>shift) & 1)
            length+=1
            symbol=decode_map.get((length, code))
            if symbol is not None:
                output.append(symbol)
                if len(output)==original_size:
                    #只能剩下最後一個byte的補零，不可有多餘資料。
                    if index != len(payload)-1 or (byte & ((1 << shift)- 1)):
                        raise ValueError("壓縮資料尾端含有多餘或非零的位元")
                    return bytes(output)
                code=0
                length=0
            elif length>max_length:
                raise ValueError("壓縮內容包含無效碼字")
    raise ValueError("壓縮資料不完整，無法還原指定的原始長度")

#產出自訂.huf格式；若Huffman無法縮小就儲存原始資料
def compress_bytes(data:bytes)->bytes:
    lengths=build_code_lengths(data)
    codes=canonical_codes(lengths)
    packed=encode_bits(data,codes)
    table=b"".join(bytes((symbol,length)) for symbol,length in sorted(lengths.items()))

    # 編碼後還須儲存碼表；加總成本若較大，就保留原始bytes(仍可無失真解壓)
    if len(table) + len(packed) < len(data):
        method=METHOD_HUFFMAN
        payload=table+packed
        count=len(lengths)
    else:
        method=METHOD_RAW
        payload=data
        count=0

    checksum=zlib.crc32(data) & 0xFFFFFFFF
    return HEADER.pack(MAGIC,method,len(data),checksum,count)+payload

#解析檔頭、重建標準碼表，還原並檢查CRC32，執行解壓縮
def decompress_bytes(blob:bytes)->bytes:
    if len(blob)<HEADER.size:
        raise ValueError("檔案過短：找不到完整檔頭")
    magic,method,original_size,checksum,count=HEADER.unpack_from(blob)
    if magic != MAGIC:
        raise ValueError("不是本程式的HUF1壓縮檔")
    if count>256:
        raise ValueError("非法的符號數量")

    if method==METHOD_RAW:
        if count != 0:
            raise ValueError("原始儲存模式不應附帶碼表")
        data=blob[HEADER.size:]
        if len(data) != original_size:
            raise ValueError("儲存資料長度不符")
    elif method==METHOD_HUFFMAN:
        start=HEADER.size
        end=start+2*count
        if len(blob)<end:
            raise ValueError("碼表資料不完整")
        pairs=[(blob[i], blob[i+1]) for i in range(start,end,2)]
        lengths=dict(pairs)
        if len(lengths) != count:
            raise ValueError("碼表包含重複符號")
        data=decode_bits(blob[end:],lengths,original_size)
    else:
        raise ValueError("未知的壓縮模式")

    if (zlib.crc32(data) & 0xFFFFFFFF)!=checksum:
        raise ValueError("CRC32檢查失敗：資料已損壞")
    return data

#壓縮單一檔案，不覆寫輸入
def compress_file(input_path:Path,output_path:Path | None = None)->Path:
    output_path=output_path or input_path.with_name(input_path.name+".huf")
    if input_path.resolve()==output_path.resolve():
        raise ValueError("輸入路徑與輸出路徑不可相同")
    output_path.write_bytes(compress_bytes(input_path.read_bytes()))
    return output_path

#解壓縮單一檔案，檔名加上.restored避免覆蓋原檔
def decompress_file(input_path:Path,output_path:Path | None = None)->Path:
    if output_path is None:
        name=input_path.name[:-4] if input_path.name.endswith(".huf") else input_path.name
        output_path=input_path.with_name(name+".restored")
    if input_path.resolve()==output_path.resolve():
        raise ValueError("輸入路徑與輸出路徑不可相同")
    restored=decompress_bytes(input_path.read_bytes())
    output_path.write_bytes(restored)
    return output_path

#壓縮→解壓縮→以SHA-256與byte比對驗證，並呈現壓縮率
def test_files(files:list[Path])->None:
    results=[]

    print(f"{'檔案':<20} {'原始(B)':>12} {'壓縮(B)':>12}" f"{'壓縮比':>10} {'節省(%)':>10} {'時間(s)':>10} {'結果':>8}")
    print("-"*95)

    for path in files:

        # 讀取原始檔案內容
        original=path.read_bytes()
        original_size=len(original)

        # 開始測量執行時間
        start=time.perf_counter()

        # 執行 Huffman 壓縮
        zipped_path=compress_file(path)

        # 執行 Huffman 解壓縮
        restored_path=decompress_file(zipped_path)

        # 計算壓縮與解壓縮的總執行時間
        elapsed=time.perf_counter()-start

        # 讀取壓縮檔案與還原檔案
        compressed_size=zipped_path.stat().st_size
        restored=restored_path.read_bytes()

        # 驗證解壓縮後的資料是否完全相同
        valid=(original==restored and hashlib.sha256(original).digest()==hashlib.sha256(restored).digest())

        # 計算壓縮比（原始大小 / 壓縮後大小）
        compression_ratio=(original_size / compressed_size if compressed_size>0 else 0)

        # 計算空間節省率
        saving_rate=((1-compressed_size / original_size)*100 if original_size>0 else 0)
        status="PASS" if valid else "FAIL"

        # 顯示每個檔案的測試結果
        print(
            f"{path.name:<20} "
            f"{original_size:>12,} "
            f"{compressed_size:>12,} "
            f"{compression_ratio:>9.2f}:1 "
            f"{saving_rate:>9.2f}% "
            f"{elapsed:>10.4f} "
            f"{status:>8}"
        )

        # 將測試數據存入 results
        results.append({
            "檔案名稱":path.name,
            "原始大小(Bytes)":original_size,
            "壓縮後大小(Bytes)":compressed_size,
            "壓縮比":round(compression_ratio,4),
            "空間節省率(%)":round(saving_rate,2),
            "執行時間(秒)":round(elapsed,4),
            "無失真驗證":status
        })

    # 自動建立 CSV 檔案
    csv_path=Path("Huffman_壓縮測試結果.csv")
    with csv_path.open("w",newline="",encoding="utf-8-sig") as f:
        writer=csv.DictWriter(
            f,fieldnames=[
                "檔案名稱",
                "原始大小(Bytes)",
                "壓縮後大小(Bytes)",
                "壓縮比",
                "空間節省率(%)",
                "執行時間(秒)",
                "無失真驗證"
            ]
        )
        # 寫入 CSV 欄位名稱
        writer.writeheader()

        # 寫入四個檔案的測試結果
        writer.writerows(results)
    print(f"\nCSV 測試報告已產生：{csv_path.resolve()}")

    # 若任何檔案驗證失敗，顯示錯誤
    if any(row["無失真驗證"]=="FAIL" for row in results):
        raise AssertionError("部分檔案未通過無失真驗證")


def main()->None:
    parser=argparse.ArgumentParser(description="實作Canonical Huffman無失真壓縮與解壓縮")
    parser.add_argument("action",choices=["compress","decompress","test"])
    parser.add_argument("files",nargs="+",type=Path,help="輸入檔案；test可一次多個")
    parser.add_argument("-o","--output",type=Path,help="單檔模式的輸出路徑")
    args=parser.parse_args()
    if args.action=="test":
        if args.output:
            parser.error("test模式不可指定 --output")
        test_files(args.files)
        return
    if len(args.files) != 1:
        parser.error("compress/decompress模式只能指定一個輸入檔案")
    
    path=args.files[0]

    if args.action=="compress":
        # 執行檔案壓縮
        result=compress_file(path,args.output)

        # 取得原始檔案與壓縮檔案的大小（Bytes）
        original_size=path.stat().st_size
        compressed_size=result.stat().st_size

        print(f"\n壓縮成功：{path.name} → {result.name}")
        print(f"原始檔案大小：{original_size:,} Bytes")
        print(f"壓縮後檔案大小：{compressed_size:,} Bytes")

        # 避免原始檔案大小為 0，造成除以零錯誤
        if original_size>0:
            if compressed_size>0:
                compression_ratio = original_size / compressed_size
                print(f"壓縮比：{compression_ratio:.2f}:1")

            saving_rate=((original_size-compressed_size) / original_size*100)
            print(f"空間節省率：{saving_rate:.2f}%")
        else:
            print("原始檔案為空，無法計算壓縮比與節省率")

    else:
        # 執行解壓縮
        result=decompress_file(path,args.output)
        print(f"\n解壓縮成功：{path.name} → {result.name}")


if __name__=="__main__":
    print("程式開始執行")
    main()
    print("程式執行結束")