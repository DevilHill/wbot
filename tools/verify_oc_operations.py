"""用临时 OC 与真实浏览器验证资源管理、入队、日志下载和窄屏布局。

先运行 oc-web 的 npm run build，再用已安装 Playwright 的 Python 执行本文件。
所有业务数据均在临时目录中，截图写入 output/playwright/oc-operations。
"""
from pathlib import Path
import re
import secrets
import sys
import tempfile
import threading

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.automation_package import build_package, create_project
from app.oc.server import create_server
from app.oc.service import OcService


def verify(root):
    service = OcService(root / 'oc')
    robot = service.agents.enroll({'device_id': 'a' * 32, 'name': '财务工作站 A',
                                   'secret': secrets.token_urlsafe(32)})
    service.agents.decide(robot['id'], 'approve')
    service.agents.status(robot)
    project = root / 'project'
    create_project(project, 'finance-report')
    service.import_package(build_package(project))
    server = create_server(service, ROOT / 'oc-web/dist', 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = ROOT / 'output/playwright/oc-operations'
    output.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))

            def navigate(section):
                page.goto(server.origin + '/#' + section)
                page.locator('.initial-loading').wait_for(state='hidden')

            def capture(name):
                page.screenshot(path=str(output / f'{name}.png'), full_page=True, animations='disabled')
                page.set_viewport_size({'width': 390, 'height': 844})
                page.wait_for_timeout(300)
                page.screenshot(path=str(output / f'{name}-narrow.png'), full_page=True, animations='disabled')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name, page.evaluate('''
                    ({width: innerWidth, scrollX, doc: document.documentElement.scrollWidth, body: document.body.scrollWidth,
                    nodes: [...document.querySelectorAll('body *')].filter(e => e.scrollWidth > 390 && !e.closest('table')).map(e => [e.className, e.scrollWidth, getComputedStyle(e).overflowX])})
                '''))
                page.set_viewport_size({'width': 1440, 'height': 1000})

            navigate('environments')
            page.get_by_role('button', name='创建环境', exact=True).click()
            page.get_by_label('环境名称').fill('财务生产环境')
            page.get_by_label('说明', exact=True).fill('处理财务报表的专用执行资源组，统一维护 Robot 成员与调度状态。')
            page.get_by_role('combobox', name=re.compile('^调度状态')).select_option('paused')
            page.get_by_role('checkbox', name='财务工作站 A', exact=False).check()
            page.get_by_role('button', name='保存环境', exact=True).click()
            page.get_by_role('dialog').wait_for(state='hidden')
            capture('environments')

            navigate('assets')
            page.get_by_role('button', name='创建 Asset', exact=True).click()
            page.get_by_label('Asset 名称').fill('报表接收部门')
            page.get_by_label('配置值').fill('财务运营组')
            page.get_by_label('说明', exact=True).fill('所有财务流程使用的部门名称；更新后仅影响新提交的作业。')
            page.get_by_role('button', name='保存 Asset', exact=True).click()
            page.get_by_role('dialog').wait_for(state='hidden')
            capture('assets')
            asset = service.store.list('assets')[0]
            environment = service.store.list('environments')[0]

            navigate('processes')
            page.get_by_role('button', name='部署流程', exact=True).click()
            page.get_by_label('流程名称', exact=True).fill('财务日报汇总')
            page.get_by_label('执行目标类型').select_option('environment')
            page.get_by_role('combobox', name=re.compile('^Environment')).select_option(environment['id'])
            page.locator('.asset-bindings select').select_option(asset['id'])
            page.get_by_role('button', name='创建部署', exact=True).click()
            page.get_by_role('dialog').wait_for(state='hidden')
            page.get_by_role('button', name='入队', exact=True).click()
            page.get_by_label('优先级').select_option('90')
            page.get_by_role('button', name='提交队列', exact=True).click()
            page.get_by_role('button', name='取消等待', exact=True).wait_for()
            job = service.store.list('jobs')[0]
            assert job['parameters']['name'] == '财务运营组'
            assert job['state'] == 'queued'
            page.get_by_role('button', name='关闭对话框').click()
            page.get_by_role('button', name='刷新数据').click()
            page.get_by_text('优先级 90', exact=False).wait_for()
            capture('queue')

            navigate('assets')
            page.get_by_role('button', name='编辑 报表接收部门', exact=True).click()
            page.get_by_label('配置值').fill('新接收部门')
            page.get_by_role('button', name='保存 Asset', exact=True).click()
            page.get_by_role('dialog').wait_for(state='hidden')
            assert service.get_job(job['id'])['parameters']['name'] == '财务运营组'
            page.get_by_role('button', name='删除 报表接收部门', exact=True).click()
            page.get_by_role('button', name='确认删除', exact=True).click()
            page.get_by_role('alert').get_by_text('资源仍被流程引用', exact=False).wait_for()
            page.keyboard.press('Escape')
            page.get_by_role('dialog').wait_for(state='hidden')
            assert page.get_by_role('button', name='删除 报表接收部门', exact=True).evaluate('e => e === document.activeElement')

            navigate('environments')
            page.get_by_role('button', name='编辑 财务生产环境', exact=True).click()
            page.get_by_role('combobox', name=re.compile('^调度状态')).select_option('enabled')
            page.get_by_role('button', name='保存环境', exact=True).click()
            page.get_by_role('dialog').wait_for(state='hidden')
            device = service.store.get('devices', robot['id'])
            service.agents.status(device)
            service.queue.dispatch()
            claim = service.agents.poll(device, {})['job']
            assert claim['id'] == job['id']
            service.agents.report(device, job['id'], {'sequence': 1, 'assistant_job_id': 'browser-check',
                'state': 'succeeded', 'started_at': job['created_at'], 'finished_at': job['created_at'] + 3,
                'result': {'department': '财务运营组'}, 'error': '',
                'log': '开始汇总财务日报\nINFO 已处理 12 条记录\n财务日报汇总完成\n'})

            navigate('jobs')
            page.get_by_role('button', name='查看 财务日报汇总 作业详情').click()
            page.locator('.log-view').get_by_text('INFO 已处理 12 条记录', exact=False).wait_for()
            page.get_by_placeholder('搜索日志内容…').fill('12')
            assert page.locator('.log-view').inner_text() == 'INFO 已处理 12 条记录'
            with page.expect_download() as download:
                page.get_by_role('button', name='下载完整日志').click()
            assert '财务日报汇总完成' in Path(download.value.path()).read_text(encoding='utf-8')
            page.get_by_placeholder('搜索日志内容…').fill('')
            capture('run-log')
            page.get_by_role('button', name='关闭对话框').click()
            navigate('devices')
            page.get_by_role('heading', name='Robot 连接').wait_for()
            capture('robots')
            assert not errors, errors
            browser.close()
        print('PASS: Environment creation/editing, Asset creation/editing, deployment binding, queued snapshot, remote claim/report, log search/download, desktop/narrow layouts; no page errors')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='wbot-oc-operations-') as directory:
        verify(Path(directory))
