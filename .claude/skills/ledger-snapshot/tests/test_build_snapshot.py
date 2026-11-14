import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
import build_snapshot as bs  # noqa: E402

DATA = {
    'portfolio': [['代號', '名稱', '總市值', '未實現損益'], ['TPE:00882', '中信中國高股息', '1', '2']],
    'tx': [['交易編號', '代號', '日期', '類型', '現金流', '資金來源', '餘額（累計）']],
    'journal': [['紀錄編號', '代號', '日期', '類別', '內容']],
    'cash': [
        ['可投資餘額（測試）'],
        ['對帳錨點日期（此日之後的交易才計入）', '2026-10-29'],
        ['錨點餘額（錨點日收盤後的帳面餘額，手填）', '0'],
        [],
        ['循環餘額（賣出、股利、再投入、換股）', '0'],
        ['新資金餘額（入金與以新資金買進）', '0'],
        ['合計可投資餘額', '0'],
        ['銀行實際餘額（手填，選填）'],
    ],
}

# 與互動版相同的標記，內容縮到最小。
MINI = '''<title>Our_Investment 交易簿</title>
<style>.tabs-in { grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 4px; }</style>
<main>
  <header>
    <p id="stamp">等待連接 Google Sheets</p>
    <button class="btn" id="refresh" type="button">重新整理</button>
  </header>
  <div id="kpis"><p class="empty">連接 Google Sheets 後，這裡會顯示總市值、未實現損益與殖利率。</p></div>
    <div class="recon">
      <div id="recon-out"><p class="meta">連接 Google Sheets 後，這裡會比對帳本餘額與銀行交割帳戶餘額。</p></div>
      <form id="recon-form" novalidate>
        <input id="bank-bal">
        <button id="recon-save" type="submit">儲存並對帳</button>
      </form>
    </div>
  <details><p>這些數字由試算表計算。</p>
      <p>記帳時手續費自動計算：股數 × 價格 × 0.1425%。</p>
  </details>
  <section data-view="entry"><form id="entry"></form></section>
</main>
<nav>
  <div class="tabs-in">
    <button class="tab" data-go="overview">總覽</button>
    <button class="tab" data-go="entry">記帳</button>
  </div>
</nav>
<script>
(() => {
  // Only the Our_Investment spreadsheet. Investment_Tracker_Core is never referenced here.
  const SHEET_ID = 'TEST_OUR_INVESTMENT_SHEET_ID';
  const SERVER = 'Google Sheets';
  const RANGES = {
    portfolio: 'Portfolio!A1:S50',
    portfolioCodes: 'Portfolio!A1:A50',
    tx: 'Transactions!A1:R200',
    cash: '資金餘額!A1:B9',
    cashBank: '資金餘額!B8:B9',
    journal: 'Stock_Journal!A1:E300',
  };
  // The connector is optional.
  const mcpReady = window.claude;
  async function callSheet() {}
  const writeRange = () => {};
  function describeError(err) {}
  // Sheet cells arrive as strings
  const COPY = { a: 1 };
  const state = {};
  function renderTickers() {}
  function renderAll() {
    setStamp(`資料時間 ${timeOf(state.loadedAt)}・直接讀取試算表`);
    renderTickers();
    renderRemovable();
    renderPending();
    renderPreview();
  }
  async function load() {
      state.nextPortfolioRow = nextRow(pv);
      state.usedTickers = await readUsedTickers();
  }
  function renderRecon() {
    let verdict = '填入銀行交割帳戶的餘額與日期，就能看出帳本有沒有漏記。';
    if (!$('bank-bal')) return;
  }
  // Entry form
  function formValues() {}
  async function onReconSubmit() { await writeRange(RANGES.cashBank, []); }
  // Milestone map.
  function renderMap() {}
  document.querySelectorAll('#type-seg button').forEach((b) => b.addEventListener('click', () => setType(b.dataset.type)));
  document.querySelectorAll('#kind-seg button').forEach((b) => b.addEventListener('click', () => {
    setKind(b.dataset.kind);
  }));
  $('ticker').addEventListener('change', () => setKind(kindOf($('ticker').value)));
  const onFormEdit = () => { clearConfirm(); renderPreview(); };
  $('entry').addEventListener('input', onFormEdit);
  $('refresh').addEventListener('click', () => { load(); });
  $('recon-form').addEventListener('submit', onReconSubmit);
  $('pend-list').addEventListener('click', (e) => {
    const b = e.target.closest('[data-pend]');
    if (b) fillPending(Number(b.dataset.pend));
  });
  $('chips').addEventListener('click', () => {});
  document.querySelectorAll('#xfer-seg button').forEach((b) => b.addEventListener('click', () => {
    state.xfer = b.dataset.xfer;
    document.querySelectorAll('#xfer-seg button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    clearConfirm();
    renderPreview();
  }));
  document.querySelectorAll('#source-seg button').forEach((b) => b.addEventListener('click', () => {
    state.source = b.dataset.source;
  }));
  $('date').value = todayISO();
  setType('Buy');
  load();
})();
</script>'''


def _with(**changes):
    data = json.loads(json.dumps(DATA))
    data.update(changes)
    return data


def test_build_strips_entry_and_connector():
    out = bs.build(MINI, DATA, '2026-10-30 22:45')
    assert '快照' in out and '<title>Our_Investment 快照</title>' in out
    for gone in ('<section data-view="entry"', 'callSheet', 'writeRange', 'window.claude', 'id="refresh"', '記帳'):
        assert gone not in out
    assert 'repeat(4, minmax(0, 1fr))' in out
    assert "$('chips').addEventListener" in out and 'renderMap' in out


def test_embeds_data_and_stamp():
    out = bs.build(MINI, DATA, '2026-10-30 22:45')
    assert json.dumps(DATA['portfolio'], ensure_ascii=False) in out
    assert 'const SNAPSHOT_AT = "2026-10-30 22:45"' in out
    assert '快照時間 ${SNAPSHOT_AT}' in out


def test_cash_range_is_mapped_to_embedded_cash():
    out = bs.build(MINI, DATA, 'x')
    assert "range.startsWith('資金') ? 'cash'" in out
    assert json.dumps(DATA['cash'], ensure_ascii=False) in out


def test_source_toggle_handler_removed():
    assert "'#source-seg button'" in MINI
    out = bs.build(MINI, DATA, 'x')
    assert '#source-seg button' not in out


def test_transfer_direction_listener_removed():
    assert "'#xfer-seg button'" in MINI and 'state.xfer = b.dataset.xfer' in MINI
    out = bs.build(MINI, DATA, 'x')
    assert '#xfer-seg' not in out and 'state.xfer' not in out
    assert "$('chips').addEventListener" in out  # 其他監聽器不受影響


def test_bank_recon_keeps_result_drops_write_form():
    out = bs.build(MINI, DATA, 'x')
    assert 'id="recon-out"' in out and 'function renderRecon' in out
    for gone in ('recon-form', 'recon-save', 'onReconSubmit', 'cashBank', 'pend-list', 'renderPending', 'fillPending'):
        assert gone not in out
    assert '尚未在交易簿填入銀行餘額' in out


def test_missing_marker_fails_instead_of_partial_output():
    with pytest.raises(bs.BuildError):
        bs.build(MINI.replace('// Milestone map.', '// renamed'), DATA, 'x')


def test_bad_data_rejected():
    with pytest.raises(bs.BuildError):
        bs.build(MINI, {'portfolio': [['a']], 'tx': []}, 'x')


def test_missing_cash_rejected():
    data = _with()
    del data['cash']
    with pytest.raises(bs.BuildError, match='cash'):
        bs.build(MINI, data, 'x')


def test_cash_label_drift_rejected():
    cash = json.loads(json.dumps(DATA['cash']))
    cash[6][0] = '總額'
    with pytest.raises(bs.BuildError, match='合計'):
        bs.build(MINI, _with(cash=cash), 'x')


def test_cash_row_shift_rejected():
    cash = [DATA['cash'][0]] + DATA['cash'][2:]
    with pytest.raises(bs.BuildError, match='錨點日期'):
        bs.build(MINI, _with(cash=cash), 'x')


def test_tx_header_drift_rejected():
    tx = [['交易編號', '代號', '日期', '類型', '餘額（累計）']]
    with pytest.raises(bs.BuildError, match='現金流'):
        bs.build(MINI, _with(tx=tx), 'x')


def test_sheet_constants_stripped_ranges_kept():
    out = bs.build(MINI, DATA, 'x')
    for gone in ('SHEET_ID', 'TEST_OUR_INVESTMENT_SHEET_ID', 'SERVER', 'Investment_Tracker_Core', 'portfolioCodes'):
        assert gone not in out
    assert 'const RANGES = {' in out and "portfolio: 'Portfolio!A1:S50'" in out


def test_core_id_never_in_output(monkeypatch):
    monkeypatch.setattr(bs, 'FORBIDDEN_IDS', ['TEST_CORE_SHEET_ID'])
    with pytest.raises(bs.BuildError):
        bs.build(MINI + '\n<!-- TEST_CORE_SHEET_ID -->', DATA, 'x')


def test_our_investment_id_never_in_output(monkeypatch):
    monkeypatch.setattr(bs, 'FORBIDDEN_IDS', ['TEST_OUR_INVESTMENT_SHEET_ID'])
    with pytest.raises(bs.BuildError):
        bs.build(MINI + '\n<!-- TEST_OUR_INVESTMENT_SHEET_ID -->', DATA, 'x')


def test_leftover_connector_token_rejected():
    with pytest.raises(bs.BuildError, match='SHEET_ID'):
        bs.build(MINI + '\n<!-- SHEET_ID -->', DATA, 'x')


def test_cli_fails_closed_without_drive_ids(tmp_path, monkeypatch):
    src, data, out = tmp_path / 's.html', tmp_path / 'd.json', tmp_path / 'o.html'
    src.write_text(MINI, encoding='utf8')
    data.write_text(json.dumps(DATA, ensure_ascii=False), encoding='utf8')
    monkeypatch.delenv('DRIVE_IDS', raising=False)
    assert bs.main(['--source', str(src), '--data', str(data), '--stamp', 't', '--out', str(out)]) == 1
    assert not out.exists()


def test_cli_roundtrip(tmp_path):
    src, data, out = tmp_path / 's.html', tmp_path / 'd.json', tmp_path / 'o.html'
    src.write_text(MINI, encoding='utf8')
    data.write_text(json.dumps(DATA, ensure_ascii=False), encoding='utf8')
    assert bs.main(['--source', str(src), '--data', str(data), '--stamp', 't', '--out', str(out)]) == 0
    assert 'SNAPSHOT' in out.read_text(encoding='utf8')
    assert bs.main(['--source', str(tmp_path / 'none'), '--data', str(data), '--stamp', 't', '--out', str(out)]) == 1


# 含既有列的資料：用來測「上一版已有的列被改或消失」。
HIST = _with(
    tx=DATA['tx'] + [['T1', 'TPE:00882', '2026-01-02', 'Buy', '-100', '循環', '0'],
                     ['T2', 'TPE:00882', '2026-01-03', 'Sell', '100', '循環', '100']],
    journal=DATA['journal'] + [['J1', 'TPE:00882', '2026-01-02', 'Trade', '賣出約獲利 80 萬']],
)


def _raw_dir(tmp_path, data=DATA, wrap=True):
    d = tmp_path / 'raw'
    d.mkdir(exist_ok=True)
    for key, sheet in bs.RAW_SHEETS.items():
        body = {'range': f"'{sheet}'!A1:Z9", 'values': data[key]} if wrap else data[key]
        (d / f'{key}.json').write_text(json.dumps(body, ensure_ascii=False), encoding='utf8')
    return d


def test_raw_dir_accepts_get_values_responses(tmp_path):
    assert bs.load_raw_dir(str(_raw_dir(tmp_path))) == DATA
    assert bs.load_raw_dir(str(_raw_dir(tmp_path, wrap=False))) == DATA


def test_raw_dir_rejects_file_from_wrong_sheet(tmp_path):
    d = _raw_dir(tmp_path)
    (d / 'tx.json').write_text(json.dumps({'range': 'Portfolio!A1:U50', 'values': DATA['tx']}), encoding='utf8')
    with pytest.raises(bs.BuildError, match='Transactions'):
        bs.load_raw_dir(str(d))


def test_history_changes_flags_edited_and_missing_rows_only():
    prev = bs.extract_snapshot(bs.build(MINI, HIST, 't'))
    assert bs.history_changes(prev, HIST) == []
    added = json.loads(json.dumps(HIST))
    added['tx'].append(['NEW1'] + [''] * (len(DATA['tx'][0]) - 1))
    assert bs.history_changes(prev, added) == []
    edited = json.loads(json.dumps(HIST))
    edited['journal'][1][-1] += '（錯字）'
    edited['tx'] = edited['tx'][:1] + edited['tx'][2:]
    found = bs.history_changes(prev, edited)
    assert len(found) == 2 and any('journal' in c for c in found) and any('這次沒有' in c for c in found)


def test_cli_prev_blocks_history_change_until_accepted(tmp_path):
    src, prev, out = tmp_path / 's.html', tmp_path / 'p.html', tmp_path / 'o.html'
    src.write_text(MINI, encoding='utf8')
    prev.write_text(bs.build(MINI, HIST, 'old'), encoding='utf8')
    edited = json.loads(json.dumps(HIST))
    edited['journal'][1][-1] += '（錯字）'
    args = ['--source', str(src), '--raw-dir', str(_raw_dir(tmp_path, edited)), '--prev', str(prev),
            '--stamp', 't', '--out', str(out)]
    assert bs.main(args) == 2 and not out.exists()
    assert bs.main(args + ['--accept-history-changes']) == 0 and out.exists()
    out.unlink()
    args[3] = str(_raw_dir(tmp_path, HIST))
    assert bs.main(args) == 0 and out.exists()


def test_cli_prev_without_embedded_data_fails(tmp_path):
    src, prev, out = tmp_path / 's.html', tmp_path / 'p.html', tmp_path / 'o.html'
    src.write_text(MINI, encoding='utf8')
    prev.write_text('<html></html>', encoding='utf8')
    args = ['--source', str(src), '--raw-dir', str(_raw_dir(tmp_path)), '--prev', str(prev), '--stamp', 't', '--out', str(out)]
    assert bs.main(args) == 1 and not out.exists()
