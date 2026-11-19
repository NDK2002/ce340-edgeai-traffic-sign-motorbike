#!/usr/bin/env python3
"""Đổi số liệu firmware D2 (bench.csv hoặc log Serial) thành bảng Markdown cho Chương 4 báo cáo.

Đầu vào: file /sdcard/bench.csv chép từ thẻ nhớ, hoặc log Serial lưu bằng
    ./05_firmware_esp32s3/pio.sh mock_inference_test device monitor | tee bench_log.txt
Chỉ đọc các dòng bắt đầu bằng "CSV," — dòng log khác được bỏ qua.

bench.csv ghi nối tiếp qua mỗi lần nạp/chạy, nên mỗi lần chạy bắt đầu bằng dòng tiêu đề "CSV,#hw,...".
Mặc định báo cáo lần chạy cuối; --run N để chọn lần khác, --list để xem danh sách.

Ví dụ:
    python3 05_firmware_esp32s3/tools/bench_report.py bench.csv -o bench_report.md
    python3 05_firmware_esp32s3/tools/bench_report.py bench.csv --charts charts/   # cần matplotlib

Chỉ dùng thư viện chuẩn của Python; vẽ biểu đồ là tùy chọn.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import OrderedDict
from pathlib import Path

SECTIONS = ("hw", "sd", "model", "camera", "pipeline", "soak")


def parse_runs(lines):
    """Tách các lần chạy. Trả về list[dict section -> list[dict cột -> giá trị chuỗi]]."""
    runs, cols, cur = [], {}, None
    for raw in lines:
        line = raw.strip().replace("\r", "")
        if not line.startswith("CSV,"):
            continue
        parts = line.split(",")
        if len(parts) < 2:
            continue
        tag = parts[1]
        if tag.startswith("#"):
            name = tag[1:]
            if name == "hw":  # tiêu đề đầu tiên của mỗi lần chạy
                cur = {s: [] for s in SECTIONS}
                runs.append(cur)
            cols[name] = parts[2:]
            continue
        if tag not in cols:
            continue  # gặp dữ liệu trước tiêu đề (file bị cắt) → bỏ qua
        if cur is None:
            cur = {s: [] for s in SECTIONS}
            runs.append(cur)
        row = dict(zip(cols[tag], parts[2:]))
        cur.setdefault(tag, []).append(row)
    return runs


def num(v, default=math.nan):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def fmt(v, digits=1):
    if isinstance(v, float):
        return "—" if math.isnan(v) else f"{v:.{digits}f}"
    return str(v)


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(fmt(c) if isinstance(c, float) else str(c) for c in r) + " |")
    return "\n".join(out)


def report(run, idx, total):
    md = [f"# Kết quả đo trên ESP32-S3 — lần chạy {idx + 1}/{total}", ""]

    if run["hw"]:
        md += ["## Phần cứng", ""]
        md.append(table(
            ["Thời điểm", "Flash (MB)", "PSRAM (MB)", "SRAM trống (KB)", "PSRAM trống (KB)", "Nhiệt độ chip (°C)"],
            [[r["stage"], r["flash_mb"], r["psram_mb"], r["free_sram_kb"], r["free_psram_kb"], num(r["temp_c"])]
             for r in run["hw"]]))
        md.append("")

    if run["sd"]:
        r = run["sd"][-1]
        md += ["## Thẻ microSD", "", f"Ghi tuần tự {r['write_kb']} KB: {num(r['kb_per_s']):.1f} KB/s.", ""]

    if run["model"]:
        models = OrderedDict()
        for r in run["model"]:
            m = models.setdefault(r["name"], {"input": r["input"], "dtype": r["dtype"], "size": num(r["size_kb"])})
            m[r["mem"]] = r
        rows = []
        for name, m in models.items():
            ps, sr = m.get("psram"), m.get("sram")
            ps_ms = num(ps["avg_ms"]) if ps else math.nan
            sr_ms = num(sr["avg_ms"]) if sr else math.nan
            arena = num((ps or sr)["arena_kb"]) if (ps or sr) else math.nan
            speed = ps_ms / sr_ms if sr_ms and not math.isnan(sr_ms) and not math.isnan(ps_ms) else math.nan
            best = min(x for x in (ps_ms, sr_ms) if not math.isnan(x)) if not (math.isnan(ps_ms) and math.isnan(sr_ms)) else math.nan
            rows.append([name, m["input"], m["dtype"], m["size"], arena, ps_ms, sr_ms,
                         "—" if math.isnan(speed) else f"×{speed:.2f}",
                         "—" if math.isnan(best) else f"{1000 / best:.1f}"])
        md += ["## So sánh model (chỉ thời gian Invoke, input rỗng)", ""]
        md.append(table(["Model", "Input", "Kiểu", "Kích thước (KB)", "Tensor Arena (KB)", "Invoke PSRAM (ms)",
                         "Invoke SRAM (ms)", "SRAM nhanh hơn", "Invoke/s tối đa"], rows))
        md += ["", "*\"—\" ở cột SRAM: arena không vừa SRAM trong, model buộc chạy trên PSRAM.*", ""]

    if run["camera"]:
        md += ["## Camera", ""]
        md.append(table(["Khung hình", "Kích thước", "Bytes/frame", "Chụp TB (ms)", "Frame OK"],
                        [[r["frame"], f"{r['width']}×{r['height']}", r["bytes"], num(r["avg_ms"], 2), r["frames_ok"]]
                         for r in run["camera"]]))
        md.append("")

    if run["pipeline"]:
        rows = [[r["model"], r["cfg"], r["frame"], r["roi"], num(r["capture_ms"]), num(r["preproc_ms"]),
                 num(r["invoke_ms"]), num(r["total_ms"]), num(r["fps"])] for r in run["pipeline"]]
        best = max(run["pipeline"], key=lambda r: num(r["fps"], 0))
        md += ["## Pipeline đầu-cuối (chụp → cắt ROI + resize → Invoke → argmax)", ""]
        md.append(table(["Model", "Phương án", "Frame", "Vùng cắt", "Chụp (ms)", "Tiền xử lý (ms)", "Invoke (ms)",
                         "Tổng (ms)", "FPS"], rows))
        md += ["", f"Nhanh nhất: **{best['cfg']}** — {num(best['fps']):.1f} FPS ({num(best['total_ms']):.1f} ms/khung).", ""]

    if run["soak"]:
        fps = [num(r["fps"]) for r in run["soak"]]
        temp = [num(r["temp_c"]) for r in run["soak"] if not math.isnan(num(r["temp_c"]))]
        psram = [num(r["free_psram_kb"]) for r in run["soak"]]
        last = run["soak"][-1]
        md += ["## Soak (chạy liên tục)", ""]
        md.append(table(["Model / phương án", "Thời gian (phút)", "FPS TB", "FPS thấp nhất", "Nhiệt độ cao nhất (°C)",
                         "PSRAM trống thấp nhất (KB)", "Số lỗi"],
                        [[f"{last['model']} / {last['cfg']}", num(last["elapsed_s"]) / 60, sum(fps) / len(fps), min(fps),
                          max(temp) if temp else math.nan, min(psram), last["errors"]]]))
        md += ["", "*Dòng tiêu thụ (mA) đọc trên USB tester trong lúc soak — ghi tay vào báo cáo.*", ""]

    return "\n".join(md)


def charts(run, outdir: Path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("Bỏ qua biểu đồ: chưa cài matplotlib (pip install matplotlib)", file=sys.stderr)
        return []
    outdir.mkdir(parents=True, exist_ok=True)
    files = []

    if run["model"]:
        names = list(OrderedDict.fromkeys(r["name"] for r in run["model"]))
        get = lambda n, mem: next((num(r["avg_ms"]) for r in run["model"] if r["name"] == n and r["mem"] == mem), 0)
        x = range(len(names))
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.bar([i - 0.2 for i in x], [get(n, "psram") for n in names], 0.4, label="Arena ở PSRAM")
        ax.bar([i + 0.2 for i in x], [get(n, "sram") for n in names], 0.4, label="Arena ở SRAM")
        ax.set_xticks(list(x), names, rotation=20, ha="right")
        ax.set_ylabel("Invoke (ms)")
        ax.legend()
        fig.tight_layout()
        files.append(outdir / "model_latency.png")
        fig.savefig(files[-1], dpi=150)
        plt.close(fig)

    if run["pipeline"]:
        cfgs = [r["cfg"] for r in run["pipeline"]]
        parts = [("capture_ms", "Chụp"), ("preproc_ms", "Tiền xử lý"), ("invoke_ms", "Invoke")]
        fig, ax = plt.subplots(figsize=(7, 4))
        bottom = [0.0] * len(cfgs)
        for key, label in parts:
            vals = [num(r[key], 0) for r in run["pipeline"]]
            ax.bar(cfgs, vals, bottom=bottom, label=label)
            bottom = [b + v for b, v in zip(bottom, vals)]
        ax.set_ylabel("ms / khung")
        ax.legend()
        fig.tight_layout()
        files.append(outdir / "pipeline_breakdown.png")
        fig.savefig(files[-1], dpi=150)
        plt.close(fig)

    if run["soak"]:
        t = [num(r["elapsed_s"]) / 60 for r in run["soak"]]
        fig, ax1 = plt.subplots(figsize=(7, 4))
        ax1.plot(t, [num(r["fps"]) for r in run["soak"]], label="FPS")
        ax1.set_xlabel("phút")
        ax1.set_ylabel("FPS")
        ax2 = ax1.twinx()
        ax2.plot(t, [num(r["temp_c"]) for r in run["soak"]], color="tab:red", label="Nhiệt độ chip")
        ax2.set_ylabel("°C")
        fig.tight_layout()
        files.append(outdir / "soak.png")
        fig.savefig(files[-1], dpi=150)
        plt.close(fig)
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input", type=Path, help="bench.csv hoặc file log Serial")
    ap.add_argument("-o", "--output", type=Path, help="file Markdown đầu ra (mặc định in ra màn hình)")
    ap.add_argument("--run", type=int, default=0, help="lần chạy thứ N (1 = đầu tiên, mặc định = cuối cùng)")
    ap.add_argument("--list", action="store_true", help="liệt kê các lần chạy có trong file")
    ap.add_argument("--charts", type=Path, help="thư mục lưu biểu đồ PNG (cần matplotlib)")
    args = ap.parse_args()

    runs = parse_runs(args.input.read_text(encoding="utf-8", errors="replace").splitlines())
    if not runs:
        sys.exit(f"Không thấy dòng 'CSV,' nào trong {args.input}")
    if args.list:
        for i, r in enumerate(runs, 1):
            print(f"{i}: " + ", ".join(f"{k}={len(v)}" for k, v in r.items() if v))
        return
    idx = (args.run - 1) if args.run > 0 else len(runs) - 1
    if not 0 <= idx < len(runs):
        sys.exit(f"Chỉ có {len(runs)} lần chạy")

    md = report(runs[idx], idx, len(runs))
    if args.charts:
        for f in charts(runs[idx], args.charts):
            md += f"\n![{f.stem}]({f.as_posix()})\n"
    if args.output:
        args.output.write_text(md + "\n", encoding="utf-8")
        print(f"Đã ghi {args.output}")
    else:
        print(md)


if __name__ == "__main__":
    main()
