import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
import build_snapshot as bs  # noqa: E402

DATA = {
    'portfolio': [['代號', '名稱'], ['TPE:00882', '中信中國高股息']],
    'tx': [['交易編號', '代號']],
    'journal': [['紀錄編號', '代號']],
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
  $('date').value = todayISO();
  setType('Buy');
  load();
})();
</script>'''


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


def test_missing_marker_fails_instead_of_partial_output():
    with pytest.raises(bs.BuildError):
        bs.build(MINI.replace('// Milestone map.', '// renamed'), DATA, 'x')


def test_bad_data_rejected():
    with pytest.raises(bs.BuildError):
        bs.build(MINI, {'portfolio': [['a']], 'tx': []}, 'x')


def test_core_id_never_in_output():
    poisoned = MINI + f'\n<!-- {bs.CORE_ID} -->'
    with pytest.raises(bs.BuildError):
        bs.build(poisoned, DATA, 'x')


def test_cli_roundtrip(tmp_path):
    src, data, out = tmp_path / 's.html', tmp_path / 'd.json', tmp_path / 'o.html'
    src.write_text(MINI, encoding='utf8')
    data.write_text(json.dumps(DATA, ensure_ascii=False), encoding='utf8')
    assert bs.main(['--source', str(src), '--data', str(data), '--stamp', 't', '--out', str(out)]) == 0
    assert 'SNAPSHOT' in out.read_text(encoding='utf8')
    assert bs.main(['--source', str(tmp_path / 'none'), '--data', str(data), '--stamp', 't', '--out', str(out)]) == 1
