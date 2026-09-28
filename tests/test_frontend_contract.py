from pathlib import Path
import re


WEB_FILES = [
    Path("app/web/index.html"),
    Path("app/web/styles.css"),
    Path("app/web/api.js"),
    Path("app/web/app.js"),
]


def test_frontend_has_no_platform_database_or_health_cache():
    source = "\n".join(path.read_text("utf-8") for path in WEB_FILES)
    assert "__SMART_PAGE__" not in source
    assert "page_comm/inject.js" not in source
    assert "data-sp-database-id" not in source
    assert "wb_personal_health_archive" not in source
    assert "localStorage.setItem" not in source


def test_frontend_exposes_required_views():
    html = Path("app/web/index.html").read_text("utf-8")
    for view in ["auth", "overview", "home", "upload", "archive", "drugs", "detail", "admin"]:
        assert f'id="view-{view}"' in html


def test_main_navigation_has_dedicated_costs_and_inline_trends():
    html = Path("app/web/index.html").read_text("utf-8")
    script = Path("app/web/v19.js").read_text("utf-8")
    nav = html.split('<nav class="nav" aria-label="主导航">', 1)[1].split('</nav>', 1)[0]
    assert re.findall(r'data-view="([^"]+)"', nav) == ['overview', 'home', 'upload', 'drugs', 'costs', 'archive']
    for label in ["数据概览", "健康档案", "上传资料", "药品管理", "医疗费用", "原始资料"]:
        assert label in nav
    for removed in ['data-view="metrics"', 'data-view="ogtt"', 'data-view="pending"']:
        assert removed not in nav
    assert 'overview-expense-panel' not in html.split('id="view-overview"', 1)[1].split('id="view-metric-detail"', 1)[0]
    assert 'overview-expense-panel' in html.split('id="view-costs"', 1)[1].split('id="view-upload"', 1)[0]
    assert 'data-view="admin"' in html.split('</nav>', 1)[1]
    assert 'id="pendingBadge"' in nav
    assert 'id="uploadPendingList"' in html
    for label in ["最新结果", "日期", "记录", "趋势"]:
        assert label in html
    assert 'id="overviewMetrics"' in html
    assert 'id="metricRecordDialog"' in html
    assert 'id="quickMetricForm"' in html
    assert 'overviewSparkline' in script
    assert 'trend_series' in script
    assert "/api/overview" in script
    batch_review = Path("app/web/batch-review.js").read_text("utf-8")
    assert "loadOverview()" in batch_review and "loadMetrics()" in batch_review
    assert "localStorage" not in script


def test_document_detail_preserves_v7_page_layout():
    html = Path("app/web/index.html").read_text("utf-8")
    styles = Path("app/web/styles.css").read_text("utf-8").replace(" ", "")

    assert 'id="detailContent"' in html
    assert 'id="filePreview"' in html
    assert 'id="labResults"' in html
    assert 'id="detailDialog"' not in html
    assert "grid-template-columns:minmax(0,1.08fr)minmax(0,.92fr)" in styles
    assert ".file-previewimg,.file-previewiframe{width:100%;height:505px" in styles


def test_home_preserves_blue_v6_filters():
    html = Path("app/web/index.html").read_text("utf-8")
    raw_styles = Path("app/web/styles.css").read_text("utf-8")
    styles = raw_styles.replace(" ", "").lower()

    for control in ["searchInput", "typeFilter", "hospitalFilter"]:
        assert f'id="{control}"' in html
    assert "--blue:#315feb" in styles
    assert ".toolbar{display:grid;grid-template-columns:minmax(240px,1fr)170px170px" in styles
    assert "\n+    /*" not in raw_styles


def test_detail_navigation_preserves_origin_and_scroll():
    html = Path("app/web/index.html").read_text("utf-8")
    script = Path("app/web/app.js").read_text("utf-8")

    assert 'id="detailBack"' in html
    assert "detailReturnView" in script
    assert "viewScroll" in script
    assert "restoreScroll" in script
    assert "returnFromDetail" in script


def test_review_preview_batch_upload_and_visible_progress():
    html = Path("app/web/index.html").read_text("utf-8")
    styles = Path("app/web/styles.css").read_text("utf-8")
    script = Path("app/web/app.js").read_text("utf-8")

    assert 'id="fileInput" type="file"' in html and " multiple" in html
    assert 'id="reviewSource"' in html
    assert '<iframe id="reviewSource"' not in html
    for element in ["uploadProgress", "uploadProgressBar", "uploadQueue"]:
        assert f'id="{element}"' in html
    assert ".progress-copy.processing" in styles
    assert "renderUploadProgress" in script
    assert "attachmentPreview" in script


def test_frontend_uses_real_api_routes():
    script = Path("app/web/app.js").read_text("utf-8")
    for route in ["/api/setup/status", "/api/uploads", "/api/drafts", "/api/documents", "/api/medications", "/api/admin/users"]:
        assert route in script


def test_api_client_does_not_shadow_its_request_function():
    script = Path("app/web/api.js").read_text("utf-8")
    assert "async function request(" in script
    assert "=>request(path" in script
    assert "async function api(" not in script


def test_root_serves_independent_workbench(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "个人健康档案工作台" in response.text
