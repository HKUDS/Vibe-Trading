"""ashare-pre-st-filter / fetch_sina_penalties.py 单元测试。

覆盖 CR P0/P1 修复点：
- HTMLParser 解析正确性（替代灾难性回溯正则）
- event_type 结构化提取（不会把"公告日期"误识别）
- subject_normalized 主体识别 + 优先级
- 日期过滤边界
- HTTP 失败时 fetch_penalty_list 返回 fallback JSON
- _validate_stockid 输入校验
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "skills"
    / "ashare-pre-st-filter"
    / "scripts"
    / "fetch_sina_penalties.py"
)


@pytest.fixture(scope="module")
def fsp():
    spec = importlib.util.spec_from_file_location("fsp", _MODULE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# _validate_stockid
# ---------------------------------------------------------------------------

class TestValidateStockid:
    def test_with_sh_suffix(self, fsp):
        assert fsp._validate_stockid("600000.SH") == "600000"

    def test_with_sz_suffix(self, fsp):
        assert fsp._validate_stockid("000001.SZ") == "000001"

    def test_bare_six_digits(self, fsp):
        assert fsp._validate_stockid("688001") == "688001"

    def test_lowercase_suffix(self, fsp):
        assert fsp._validate_stockid("300750.sz") == "300750"

    def test_empty_raises(self, fsp):
        with pytest.raises(ValueError):
            fsp._validate_stockid("")

    def test_invalid_length_raises(self, fsp):
        with pytest.raises(ValueError):
            fsp._validate_stockid("60000")


# ---------------------------------------------------------------------------
# _normalize_subject —— 主体识别 + 优先级
# ---------------------------------------------------------------------------

class TestNormalizeSubject:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("某公司未及时披露关联交易", "company"),
            ("控股股东张三违规减持", "shareholder"),
            ("XX 公司原董事长李四短线交易", "officer"),
            ("实际控制人内幕交易", "shareholder"),
            ("财务总监未履行勤勉尽责义务", "officer"),
            ("证券事务代表信息披露违规", "officer"),
            ("一致行动人未及时披露权益变动", "shareholder"),
            ("5%以上股东减持未预披露", "shareholder"),
            ("聘任的高级管理人员违规交易", "officer"),
            ("", "company"),
        ],
    )
    def test_keyword_match(self, fsp, text, expected):
        assert fsp._normalize_subject(text) == expected

    def test_priority_shareholder_over_officer(self, fsp):
        # 身份叠加：董事长 + 控股股东 → 取更重责任主体 shareholder
        text = "董事长 X 作为控股股东违规减持"
        assert fsp._normalize_subject(text) == "shareholder"


# ---------------------------------------------------------------------------
# _extract_event_type / _build_record —— event_type 不会误识别"公告日期"
# ---------------------------------------------------------------------------

class TestExtractEventType:
    def test_normal_warning(self, fsp):
        assert fsp._extract_event_type("警示函 公告日期 2024-05-12") == "警示函"

    def test_skip_date_literal(self, fsp):
        # 黑名单兜底：head 文本里只剩"公告日期"时不应当作 event_type
        assert fsp._extract_event_type("公告日期") == "未分类"

    def test_skip_label_then_pick_real_type(self, fsp):
        # 假设新浪改版把"类型"当字面量放在前面
        assert fsp._extract_event_type("类型 监管关注") == "监管关注"

    def test_no_chinese_returns_default(self, fsp):
        assert fsp._extract_event_type("2024-05-12") == "未分类"


# ---------------------------------------------------------------------------
# _parse_penalty_list —— HTMLParser 端到端解析
# ---------------------------------------------------------------------------

_FIXTURE_HTML = """
<html><body>
<table id="collectFund_1">
  <thead><tr><th>警示函 公告日期: 2024-05-12</th></tr></thead>
  <tr><td><strong>标题:</strong></td><td>关于对某公司的警示函</td></tr>
  <tr><td><strong>批复原因:</strong></td><td>未及时披露关联交易</td></tr>
  <tr><td><strong>批复内容:</strong></td><td>责令改正</td></tr>
  <tr><td><strong>处理人:</strong></td><td>上海证券交易所</td></tr>

  <thead><tr><th>监管关注 公告日期: 2024-08-20</th></tr></thead>
  <tr><td><strong>标题:</strong></td><td>关于对控股股东张三的监管关注函</td></tr>
  <tr><td><strong>批复原因:</strong></td><td>违规减持</td></tr>
  <tr><td><strong>批复内容:</strong></td><td>提请关注</td></tr>
  <tr><td><strong>处理人:</strong></td><td>深圳证券交易所</td></tr>

  <thead><tr><th>处罚 公告日期: 2025-02-01</th></tr></thead>
  <tr><td><strong>标题:</strong></td><td>对 XX 公司原董事长李四的行政处罚</td></tr>
  <tr><td><strong>处罚原因:</strong></td><td>短线交易</td></tr>
  <tr><td><strong>处罚内容:</strong></td><td>罚款 50 万元</td></tr>
  <tr><td><strong>处罚机关:</strong></td><[email protected]>北京证监局</td></tr>
</table>
</body></html>
""".replace("[email protected]", "td")


class TestParsePenaltyList:
    def test_parses_three_records(self, fsp):
        recs = fsp._parse_penalty_list(_FIXTURE_HTML)
        assert len(recs) == 3

    def test_record_schema(self, fsp):
        rec = fsp._parse_penalty_list(_FIXTURE_HTML)[0]
        expected_keys = {
            "ann_date", "event_type", "title", "reason",
            "reason_normalized", "content", "issuer",
            "issuer_normalized", "subject_normalized",
        }
        assert expected_keys.issubset(rec.keys())

    def test_event_type_extracted(self, fsp):
        recs = fsp._parse_penalty_list(_FIXTURE_HTML)
        assert recs[0]["event_type"] == "警示函"
        assert recs[1]["event_type"] == "监管关注"
        # 不会出现"公告日期"被当作 event_type
        for r in recs:
            assert r["event_type"] != "公告日期"

    def test_ann_date_normalized(self, fsp):
        recs = fsp._parse_penalty_list(_FIXTURE_HTML)
        assert recs[0]["ann_date"] == "2024-05-12"
        assert recs[2]["ann_date"] == "2025-02-01"

    def test_subject_classification(self, fsp):
        recs = fsp._parse_penalty_list(_FIXTURE_HTML)
        # 第 1 条：公司本身
        assert recs[0]["subject_normalized"] == "company"
        # 第 2 条：含"控股股东" → shareholder
        assert recs[1]["subject_normalized"] == "shareholder"
        # 第 3 条：含"原董事长" → officer
        assert recs[2]["subject_normalized"] == "officer"

    def test_issuer_normalized(self, fsp):
        recs = fsp._parse_penalty_list(_FIXTURE_HTML)
        assert recs[0]["issuer_normalized"] == "上交所"
        assert recs[1]["issuer_normalized"] == "深交所"
        # 地方证监局优先于证监会
        assert recs[2]["issuer_normalized"] == "地方证监局"

    def test_empty_html(self, fsp):
        assert fsp._parse_penalty_list("<html></html>") == []

    def test_no_target_table(self, fsp):
        html = '<table id="other"><tr><td>noise</td></tr></table>'
        assert fsp._parse_penalty_list(html) == []


# ---------------------------------------------------------------------------
# _apply_date_filter —— 日期过滤边界
# ---------------------------------------------------------------------------

class TestApplyDateFilter:
    def _records(self):
        return [
            {"ann_date": "2024-01-01", "title": "a"},
            {"ann_date": "2024-06-15", "title": "b"},
            {"ann_date": "2024-12-31", "title": "c"},
            {"ann_date": "", "title": "no-date"},
        ]

    def test_no_filter_returns_all(self, fsp):
        out = fsp._apply_date_filter(self._records(), None, None)
        assert len(out) == 4

    def test_inclusive_endpoints(self, fsp):
        out = fsp._apply_date_filter(self._records(), "2024-01-01", "2024-12-31")
        # 端点应该被包含；缺失日期记录也保留并打 _warning
        titles = {r["title"] for r in out}
        assert {"a", "b", "c", "no-date"} == titles

    def test_start_only(self, fsp):
        out = fsp._apply_date_filter(self._records(), "2024-06-01", None)
        assert {r["title"] for r in out if r["title"] != "no-date"} == {"b", "c"}

    def test_end_only(self, fsp):
        out = fsp._apply_date_filter(self._records(), None, "2024-06-15")
        assert {r["title"] for r in out if r["title"] != "no-date"} == {"a", "b"}

    def test_missing_date_marked(self, fsp):
        out = fsp._apply_date_filter(self._records(), "2024-01-01", "2024-12-31")
        no_date = [r for r in out if r["title"] == "no-date"][0]
        assert no_date.get("_warning") == "missing_ann_date"


# ---------------------------------------------------------------------------
# fetch_penalty_list —— HTTP 失败 / host 校验失败时的 fallback
# ---------------------------------------------------------------------------

class TestFetchPenaltyListFallback:
    def test_invalid_ts_code_raises(self, fsp):
        # _validate_stockid 在 fetch_penalty_list 顶部调用，无效输入直接抛
        with pytest.raises(ValueError):
            fsp.fetch_penalty_list("INVALID")

    def test_http_failure_returns_fallback(self, fsp, monkeypatch):
        def _boom(url, *, timeout=15):
            raise RuntimeError("http get failed: simulated")

        monkeypatch.setattr(fsp, "_http_get_gbk", _boom)
        result = fsp.fetch_penalty_list("600000.SH")
        assert result["source"] == "unavailable"
        assert "http_failed" in result["error"]
        assert result["records"] == []
        # 仍包含 ts_code / url 上下文
        assert result["ts_code"] == "600000.SH"

    def test_parse_failure_returns_fallback(self, fsp, monkeypatch):
        monkeypatch.setattr(fsp, "_http_get_gbk", lambda *a, **kw: "<html></html>")

        def _boom(html):
            raise RuntimeError("parse exploded")

        monkeypatch.setattr(fsp, "_parse_penalty_list", _boom)
        result = fsp.fetch_penalty_list("600000.SH")
        assert result["source"] == "unavailable"
        assert "parse_failed" in result["error"]


# ---------------------------------------------------------------------------
# 抗灾难性回溯：脏 HTML 不应卡死
# ---------------------------------------------------------------------------

class TestNoCatastrophicBacktracking:
    def test_unclosed_tr_does_not_hang(self, fsp):
        """未闭合 <tr> 的脏 HTML，旧灾难性正则在此会指数级回溯。

        新 HTMLParser 实现应在毫秒级完成。
        """
        import time

        dirty = (
            '<table id="collectFund_1">'
            + '<thead><tr><th>警示函 公告日期: 2024-05-12</th></tr></thead>'
            + ('<tr><td><strong>标题</strong></td><td>x</td>' * 200)  # 故意不闭合 </tr>
            + "</table>"
        )
        t0 = time.perf_counter()
        recs = fsp._parse_penalty_list(dirty)
        elapsed = time.perf_counter() - t0
        # 即便解析结果数为 0 也无所谓，关键是不能卡死
        assert elapsed < 1.0, f"parsing dirty html took {elapsed:.3f}s — possible regex backtracking"
        assert isinstance(recs, list)


# ---------------------------------------------------------------------------
# P2: 全半角 / 大小写归一
# ---------------------------------------------------------------------------

class TestNormalizeFullwidth:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("５％以上股东减持未预披露", "shareholder"),  # 全角数字+全角百分号
            ("控股 股东 张三", "shareholder"),            # 含全角空格
            ("董\u3000秘违规交易", "officer"),            # 全角空格在词中
            ("ＤＤ公司未及时披露", "company"),            # 全角字母不影响
        ],
    )
    def test_subject_with_fullwidth(self, fsp, text, expected):
        assert fsp._normalize_subject(text) == expected

    def test_reason_with_fullwidth(self, fsp):
        assert fsp._normalize_reason("信　息　披　露 违规") == "信息披露违规"

    def test_issuer_with_fullwidth(self, fsp):
        assert fsp._normalize_issuer("上 海 证 券 交 易 所") == "上交所"


# ---------------------------------------------------------------------------
# P2: _RecordParser 边界 / thead 嵌套 / 多空白
# ---------------------------------------------------------------------------

class TestRecordParserEdgeCases:
    def test_nested_strong_in_value(self, fsp):
        """value td 内包含 <strong> 嵌套时，不应被误当作下一行 key。"""
        html = (
            '<table id="collectFund_1">'
            '<thead><tr><th>警示函 公告日期: 2024-01-01</th></tr></thead>'
            '<tr><td><strong>标题:</strong></td><td>关于 <strong>重要</strong> 事项的警示函</td></tr>'
            '<tr><td><strong>批复原因:</strong></td><td>违规减持</td></tr>'
            '</table>'
        )
        recs = fsp._parse_penalty_list(html)
        assert len(recs) == 1
        assert "重要" in recs[0]["title"]
        assert recs[0]["reason"] == "违规减持"

    def test_extra_whitespace_in_thead(self, fsp):
        html = (
            '<table id="collectFund_1">'
            '<thead><tr><th>  \n\t 监管关注\n  公告日期:  2024-08-20  </th></tr></thead>'
            '<tr><td><strong>标题:</strong></td><td>x</td></tr>'
            '<tr><td><strong>批复原因:</strong></td><td>y</td></tr>'
            '</table>'
        )
        recs = fsp._parse_penalty_list(html)
        assert len(recs) == 1
        assert recs[0]["event_type"] == "监管关注"
        assert recs[0]["ann_date"] == "2024-08-20"

    def test_record_without_strong_dropped(self, fsp):
        """完全没有 strong key 的 thead 段（无任何字段），_build_record 返回 None。"""
        html = (
            '<table id="collectFund_1">'
            '<thead><tr><th>警示函 公告日期: 2024-05-12</th></tr></thead>'
            '<tr><td>noise</td><td>noise</td></tr>'
            '</table>'
        )
        assert fsp._parse_penalty_list(html) == []

    def test_multiple_td_after_key_only_first_taken(self, fsp):
        """key 后出现多个 td 时，只取第一个作为 value。"""
        html = (
            '<table id="collectFund_1">'
            '<thead><tr><th>警示函 公告日期: 2024-05-12</th></tr></thead>'
            '<tr><td><strong>标题:</strong></td><td>真实标题</td><td>多余的td</td></tr>'
            '<tr><td><strong>批复原因:</strong></td><td>r</td></tr>'
            '</table>'
        )
        recs = fsp._parse_penalty_list(html)
        assert recs[0]["title"] == "真实标题"

    def test_no_thead_returns_empty(self, fsp):
        html = (
            '<table id="collectFund_1">'
            '<tr><td><strong>标题:</strong></td><td>x</td></tr>'
            '</table>'
        )
        assert fsp._parse_penalty_list(html) == []
