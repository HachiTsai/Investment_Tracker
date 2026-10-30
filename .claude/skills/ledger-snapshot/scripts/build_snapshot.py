#!/usr/bin/env python3
"""由互動版交易簿頁面衍生唯讀快照頁。

用法：
  python3 build_snapshot.py --source ledger.html --data data.json --stamp "2026-10-30 22:45" --out snap.html

來源頁是互動版 Artifact 的 HTML。快照保留除「記帳」以外的分頁，拿掉連接器與所有寫入程式，
並把試算表的值內嵌進頁面。只用標準函式庫；不讀也不寫任何試算表。
data.json 的格式：{"portfolio": [[...]], "tx": [[...]], "journal": [[...]]}，
值為 Sheets get_values 回傳的二維陣列（含表頭列）。
"""
import argparse
import json
import re
import sys

DATA_KEYS = ('portfolio', 'tx', 'journal')
# Core 的試算表 ID：快照頁永遠不該出現，出現就中止。
CORE_ID = '1QBEgUi-kTOuLgj2yGHmP-0g_ug-Sl_M21SN0g93b6xI'


class BuildError(Exception):
    pass


def _cut(s, start, end, keep_end=True):
    a = s.find(start)
    if a < 0:
        raise BuildError(f'找不到起點標記：{start!r}')
    b = s.find(end, a)
    if b < 0:
        raise BuildError(f'找不到終點標記：{end!r}')
    return s[:a] + (s[b:] if keep_end else s[b + len(end):])


def _sub(s, old, new):
    if old not in s:
        raise BuildError(f'找不到要取代的內容：{old!r}')
    return s.replace(old, new, 1)


def _sub_re(s, pattern, new, flags=0):
    s, n = re.subn(pattern, new, s, flags=flags)
    if n < 1:
        raise BuildError(f'找不到符合的內容：{pattern!r}')
    return s


def validate_data(data):
    for key in DATA_KEYS:
        rows = data.get(key)
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], list):
            raise BuildError(f'data.json 缺少 {key} 或格式不對（需含表頭列的二維陣列）')


def build(source, data, stamp):
    """回傳快照頁 HTML。來源頁改版導致標記找不到時丟出 BuildError，不輸出半成品。"""
    validate_data(data)
    s = source
    # HTML：拿掉記帳分頁、分頁按鈕與重新整理
    s = _cut(s, '  <section data-view="entry"', '</main>')
    s = _sub_re(s, r'\n    <button class="tab"[^\n]*data-go="entry"[^\n]*</button>', '')
    s = _sub(s, 'repeat(5, minmax(0, 1fr)); gap: 4px', 'repeat(4, minmax(0, 1fr)); gap: 4px')
    s = _sub(s, '    <button class="btn" id="refresh" type="button">重新整理</button>\n', '')
    s = _sub(s, '<title>Our_Investment 交易簿</title>', '<title>Our_Investment 快照</title>')
    s = _sub(s, '等待連接 Google Sheets', '讀取快照中')
    s = _sub(s, '連接 Google Sheets 後，這裡會顯示總市值、未實現損益與殖利率。', '這裡會顯示總市值、未實現損益與殖利率。')
    s = _sub_re(s, r'\n?\s*<p>記帳時手續費自動計算.*?</p>', '')
    # JS 資料層：連接器換成內嵌資料
    embedded = (
        f'  const SNAPSHOT = {json.dumps(data, ensure_ascii=False)};\n'
        f'  const SNAPSHOT_AT = {json.dumps(stamp, ensure_ascii=False)};\n'
        "  const readRange = async (range) => SNAPSHOT[range.startsWith('Portfolio') ? 'portfolio' : "
        "range.startsWith('Transactions') ? 'tx' : 'journal'];\n"
        "  const describeError = (err) => (err && err.message) || '讀取快照失敗。';\n\n"
    )
    s = _cut(s, '  // The connector is optional.', '  // Sheet cells arrive')
    s = _sub(s, '  // Sheet cells arrive', embedded + '  // Sheet cells arrive')
    s = _cut(s, '  const COPY = {', '  const state = {')
    # JS：拿掉記帳、新增與移除標的的程式
    s = _cut(s, '  function renderTickers() {', '  function renderAll')
    s = _cut(s, '  // Entry form', '  // Milestone map.')
    s = _sub(s, '      state.nextPortfolioRow = nextRow(pv);\n', '')
    s = _sub(s, '      state.usedTickers = await readUsedTickers();\n', '')
    s = _sub(s, '    renderTickers();\n    renderRemovable();\n    renderPreview();\n', '')
    s = _sub(s, 'setStamp(`資料時間 ${timeOf(state.loadedAt)}・直接讀取試算表`);',
             'setStamp(`快照時間 ${SNAPSHOT_AT}・唯讀，由 Claude 定時更新`);')
    for pattern in (
        r"  document\.querySelectorAll\('#type-seg button'\)[^\n]*\n",
        r"  document\.querySelectorAll\('#kind-seg button'\)\.forEach\(.*?\n  \}\)\);\n",
        r"  \$\('ticker'\)\.addEventListener[^\n]*\n",
        r"  const onFormEdit[^\n]*\n",
        r"  \$\('(entry|confirm-yes|confirm-no|new-ticker|ticker-confirm-yes|ticker-confirm-no|remove-ticker|"
        r"remove-select|remove-confirm-yes|remove-confirm-no|refresh)'\)\.addEventListener[^\n]*\n",
        r"  \$\('date'\)\.value = todayISO\(\);\n  setType\('Buy'\);\n",
    ):
        s = _sub_re(s, pattern, '', re.S)
    # 事後檢查：不可殘留寫入、連接器或 Core
    for banned in ('callSheet', 'writeRange', 'update_values', "window.claude", CORE_ID, '<section data-view="entry"'):
        if banned in s:
            raise BuildError(f'快照殘留不該出現的內容：{banned}')
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--source', required=True, help='互動版頁面 HTML')
    ap.add_argument('--data', required=True, help='試算表資料 JSON')
    ap.add_argument('--stamp', required=True, help='快照時間（台北），例：2026-10-30 22:45')
    ap.add_argument('--out', required=True, help='輸出的快照 HTML')
    args = ap.parse_args(argv)
    try:
        with open(args.source, encoding='utf8') as f:
            source = f.read()
        with open(args.data, encoding='utf8') as f:
            data = json.load(f)
        html = build(source, data, args.stamp)
    except (BuildError, OSError, json.JSONDecodeError) as err:
        print(f'失敗：{err}', file=sys.stderr)
        return 1
    with open(args.out, 'w', encoding='utf8') as f:
        f.write(html)
    print(f'已輸出 {args.out}（{len(html):,} 字元）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
