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
    cash: '資金餘額!A1:B8',
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
    renderPreview();
  }
  async function load() {
      state.nextPortfolioRow = nextRow(pv);
      state.usedTickers = await readUsedTickers();
  }
  // Entry form
  function formValues() {}
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
