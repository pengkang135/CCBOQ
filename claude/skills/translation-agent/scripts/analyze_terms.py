import pandas as pd
import re
import argparse
import json
import os
from collections import Counter
import jieba.posseg as pseg
import jieba

def is_chinese(text):
    return re.search(r'[\u4e00-\u9fff]', text) is not None

def extract_terms(file_path, col_idx, top_n=50, output_file=None):
    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}")
        return

    print(f"Reading {file_path}...")
    try:
        df = pd.read_excel(file_path, header=0, engine='openpyxl') # Assume header exists
    except Exception as e:
        print(f"Error reading Excel: {e}")
        return

    if col_idx >= len(df.columns):
        print(f"Error: Column index {col_idx} out of bounds.")
        return

    text_list = df.iloc[:, col_idx].dropna().astype(str).tolist()
    
    if not text_list:
        print("No text found in specified column.")
        return

    # Simple language detection based on first non-empty item
    sample_text = next((t for t in text_list if t.strip()), "")
    is_zh = is_chinese(sample_text)
    
    print(f"Detected Language: {'Chinese' if is_zh else 'English'}")

    words = []
    if is_zh:
        print("Using jieba for Chinese tokenization...")
        for text in text_list:
            # Filter for nouns (n, vn, ns, nt, nz)
            words.extend([word for word, flag in pseg.cut(text) if flag.startswith('n')])
    else:
        print("Using regex for English tokenization...")
        stop_words = {"the", "and", "of", "to", "in", "a", "for", "on", "with", "as", "by", "at", "an", "be", "this", "that", "from", "or", "is", "are", "was", "were"}
        for text in text_list:
            # Split by non-word chars
            tokens = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
            words.extend([t for t in tokens if t not in stop_words])

    # Count frequency
    counter = Counter(words)
    common_terms = counter.most_common(top_n)

    result = {
        "language": "zh" if is_zh else "en",
        "total_terms": len(counter),
        "top_terms": [{"term": term, "count": count} for term, count in common_terms]
    }

    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=4, ensure_ascii=False)
        print(f"Terms saved to {output_file}")
    else:
        print(json.dumps(result, indent=4, ensure_ascii=False))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract frequent terms from Excel column.")
    parser.add_argument("file_path", help="Path to Excel file")
    parser.add_argument("--col", type=int, default=1, help="Column index (0-based)")
    parser.add_argument("--top", type=int, default=50, help="Number of top terms to extract")
    parser.add_argument("--output", help="Output JSON file path")

    args = parser.parse_args()
    extract_terms(args.file_path, args.col, args.top, args.output)
