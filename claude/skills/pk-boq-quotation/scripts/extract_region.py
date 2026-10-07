#!/usr/bin/env python
"""
区域裁图 + OCR —— 三级提取路径的第 3 级，用于关键字段核验。

为什么要裁图：全页视觉转录一次 6 分钟、95k tokens，而落款块只占页面几十分之一。
裁出来再看，token 降一个量级，准确率反而更高（paddleocr 在小区域上 4/4 命中）。

典型用途：确认落款联系方式、看有没有日期栏、核对某个存疑价格、验证盖章。

**首选 --find：位置是算出来的，不是看出来的。** 整页 rapidocr 粗读（2.6s、零 token）
拿到带坐标的文本行，匹配关键词就知道目标在哪，自动裁切并精读——全程不出图。
原本"先看缩略图挑坐标"那一步是工具缺陷逼出来的，不是任务需要。

    # 自动定位 + 出文本，一张图都不读（推荐）
    python extract_region.py quote.pdf --page 1 --find "电话|Tel|地址|签字" --ocr paddle

    # 已知坐标时直接裁
    python extract_region.py quote.pdf --page 1 --rel 0,0.6,1,0.4 --ocr paddle

    # 兜底：版面太怪、--find 找不到时，才看一眼缩略图挑坐标
    python extract_region.py quote.pdf --page 1 --thumb

输出里 rapidocr 读中文准、paddleocr 读数字准，--find 会把两份并排打出来互为校验。

裁图存到 --out-dir（默认源文件同级 raw/），**它是留痕，不要 Read**——
要内容看打印的文本行，那是 1k 级别，读图是 10 万级别。
"""
import sys, io, os, argparse
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')


def load_page_image(src, page_no, dpi):
    """PDF 渲染指定页；图片文件直接读。返回 PIL.Image"""
    from PIL import Image
    ext = Path(src).suffix.lower()
    if ext == '.pdf':
        import fitz
        doc = fitz.open(src)
        if page_no < 1 or page_no > len(doc):
            raise SystemExit(f'页码越界：PDF 共 {len(doc)} 页，请求第 {page_no} 页')
        pix = doc[page_no - 1].get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes('png'))).convert('RGB')
        doc.close()
        return img
    return Image.open(src).convert('RGB')


def run_ocr(img, engine):
    """返回识别出的文本行列表。两个引擎的取舍见 SKILL.md 的实测表。"""
    import numpy as np
    arr = np.array(img)

    if engine == 'rapid':
        from rapidocr_onnxruntime import RapidOCR
        res, _ = RapidOCR()(arr)
        return [r[1] for r in (res or [])]

    if engine == 'rapid_boxed':
        # 带坐标的粗读，供 --find 自动定位用。2.6s、零 token
        from rapidocr_onnxruntime import RapidOCR
        res, _ = RapidOCR()(arr)
        out = []
        for r in (res or []):
            pts = [(float(p[0]), float(p[1])) for p in r[0]]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            out.append({'text': r[1], 'box': (min(xs), min(ys), max(xs), max(ys))})
        return out

    # paddle：更准（唯一读对邮箱的），但慢 15 倍，所以只喂裁图别喂全页。
    # 本机必须关掉 mkldnn —— 默认 onednn 后端会在推理时崩
    from paddleocr import PaddleOCR
    try:
        ocr = PaddleOCR(lang='en', enable_mkldnn=False)
    except (TypeError, ValueError):
        ocr = PaddleOCR(lang='en')
    lines = []
    if hasattr(ocr, 'predict'):
        for page in (ocr.predict(arr) or []):
            d = page if isinstance(page, dict) else getattr(page, 'json', {})
            d = d.get('res', d) if isinstance(d, dict) else d
            lines.extend(d.get('rec_texts', []) or [])
    else:
        for page in (ocr.ocr(arr) or []):
            for item in (page or []):
                lines.append(item[1][0])
    return lines


def locate_by_text(img, pattern, pad):
    """
    先整页粗读拿坐标，再算出目标区域——**位置是算出来的，不是看出来的**。

    这是 --thumb 存在的理由被消掉的地方：原本要人看一眼缩略图才能给 --rel，
    而 OCR 本来就返回带坐标的文本行，匹配到关键词就知道它在哪。全程不出图。
    """
    import re as _re
    rx = _re.compile(pattern, _re.I)
    lines = run_ocr(img, 'rapid_boxed')
    hits = [l for l in lines if rx.search(l['text'])]
    if not hits:
        return None, lines, []
    W, H = img.size
    x0 = min(h['box'][0] for h in hits)
    y0 = min(h['box'][1] for h in hits)
    x1 = max(h['box'][2] for h in hits)
    y1 = max(h['box'][3] for h in hits)
    px, py = pad * W, pad * H
    x0, y0 = max(0, x0 - px), max(0, y0 - py)
    x1, y1 = min(W, x1 + px), min(H, y1 + py)
    region = (round(x0), round(y0), round(x1 - x0), round(y1 - y0))
    # 区域内的全部 rapid 行——rapid 中文准、paddle 只擅长数字，两份并排就是免费的交叉校验
    inside = [l for l in lines
              if l['box'][0] >= x0 - 1 and l['box'][2] <= x1 + 1
              and l['box'][1] >= y0 - 1 and l['box'][3] <= y1 + 1]
    return region, hits, inside


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('src')
    ap.add_argument('--page', type=int, default=1)
    ap.add_argument('--dpi', type=int, default=200)
    ap.add_argument('--bbox', help='绝对像素 x,y,w,h')
    ap.add_argument('--rel', help='相对坐标 x,y,w,h（0~1），无需先知道页面尺寸')
    ap.add_argument('--find', help='按关键词正则自动定位区域（如 "电话|Tel|Date|签字"）。'
                                   '不用先看缩略图挑坐标，位置由 OCR 坐标算出')
    ap.add_argument('--pad', type=float, default=0.04, help='--find 命中区域外扩比例，默认 0.04')
    ap.add_argument('--ocr', choices=['paddle', 'rapid', 'none'], default='none')
    ap.add_argument('--thumb', action='store_true', help='只出整页缩略图用于定位，不 OCR')
    ap.add_argument('--out-dir', default=None)
    ap.add_argument('--tag', default='', help='输出文件名后缀，便于区分多次裁切')
    args = ap.parse_args()

    src = Path(args.src)
    if not src.exists():
        raise SystemExit(f'找不到: {src}')

    out_dir = Path(args.out_dir) if args.out_dir else src.parent / 'raw'
    out_dir.mkdir(parents=True, exist_ok=True)

    # 缩略图只用来肉眼挑坐标，不需要看清字，72dpi 够了且比 90dpi 省一半
    dpi = 72 if args.thumb else args.dpi
    img = load_page_image(str(src), args.page, dpi)
    W, H = img.size
    print(f'源: {src.name}  第 {args.page} 页  {dpi}dpi  {W}x{H}')

    region = None
    if args.thumb:
        pass
    elif args.find:
        region, hits, inside = locate_by_text(img, args.find, args.pad)
        if region is None:
            print(f'[!] 整页粗读 {len(hits)} 行，没有匹配 "{args.find}" 的内容。')
            print('    换个关键词，或确认这页确实有该信息。**不要改去读整页图**。')
            raise SystemExit(1)
        print(f'自动定位命中 {len(hits)} 行 → 区域 {region}（由 OCR 坐标算出，未读图）\n')
        print(f'区域内 rapidocr 读数（中文准，共 {len(inside)} 行）：')
        for l in inside:
            print(f'    {l["text"]}')
    elif args.rel:
        try:
            x, y, w, h = (float(v) for v in args.rel.split(','))
        except ValueError:
            raise SystemExit('--rel 格式应为 x,y,w,h（0~1 之间的小数）')
        region = (round(x * W), round(y * H), round(w * W), round(h * H))
    elif args.bbox:
        try:
            region = tuple(int(v) for v in args.bbox.split(','))
        except ValueError:
            raise SystemExit('--bbox 格式应为 x,y,w,h（整数像素）')

    if region:
        x, y, w, h = region
        x, y = max(0, x), max(0, y)
        w, h = min(w, W - x), min(h, H - y)
        if w <= 0 or h <= 0:
            raise SystemExit(f'裁切区域无效：{region}，页面 {W}x{H}')
        img = img.crop((x, y, x + w, y + h))
        print(f'裁切: x={x} y={y} w={w} h={h}  →  {img.size[0]}x{img.size[1]}'
              f'（占整页 {w * h / (W * H) * 100:.1f}%）')

    # 存 jpg 不存 png：这张图是要进 LLM 上下文的，无损 png 比 jpg 大 3-7 倍，
    # 而定位和肉眼核验根本不需要无损。OCR 跑在内存数组上，不受这里的压缩影响。
    suffix = '_thumb' if args.thumb else (f'_crop{args.tag}' if region else f'_p{args.page}')
    out = out_dir / f'{src.stem}{suffix}.jpg'
    img.save(out, 'JPEG', quality=60 if args.thumb else 72, optimize=True)
    kb = out.stat().st_size / 1024
    est = int(kb * 1024 * 1.37 / 4)
    print(f'图片: {out}  ({kb:.0f} KB，Read 进上下文约 {est:,} tokens)')

    if args.thumb:
        print('用 Read 工具看这张缩略图定位目标区域，再用 --rel 裁出来精读。')
        print('这是唯一需要 Read 图的场景——挑完坐标就别再读它了。')
    elif args.ocr == 'none':
        # 裁了图却不 OCR，下一步多半就是 Read 它——那正是最贵的做法
        print(f'\n[!] 没有指定 --ocr，这张图只是留痕。**不要 Read 它**（约 {est:,} tokens）。')
        print(f'    要拿这块区域的内容，重跑一次加 --ocr paddle，看打印的文本行——不到 1k tokens。')

    if est > 30000:
        print(f'\n[!] 这张图偏大（约 {est:,} tokens）。如果确实要 Read，先想想能不能：')
        print('    缩小 --rel 范围 / 降低 --dpi / 改用 --ocr 出文本。')

    if args.ocr != 'none' and not args.thumb:
        import time
        t = time.time()
        lines = run_ocr(img, args.ocr)
        print(f'\nOCR({args.ocr}) {time.time() - t:.1f}s，{len(lines)} 行：')
        for ln in lines:
            print('  ' + ln)
        print('\n提醒：OCR 结果不能作为价格来源 —— 本地引擎实测最好也只读对 4/6 个价格。')
        print('价格取自数据源（Excel/有文本层 PDF），这里只用于核对联系方式、日期、盖章。')
        print('核验联系方式/日期/盖章：上面这些文本行就是全部证据，**不要再 Read 那张图**。')
        print('一张整页图进上下文 10-16 万 tokens，这段文本不到 1k —— 差两个数量级。')


if __name__ == '__main__':
    main()
