"""首页底部 Tab 与各工具路由的映射。"""

VALID_HOME_TABS = frozenset({'aux', 'mod', 'download'})

PATH_HOME_TAB = {
    '/tools': 'aux',
    '/deck-editor': 'aux',
    '/card-sender': 'aux',
    '/pack-buyer': 'aux',
    '/diamond-tool': 'aux',
    '/unity': 'mod',
    '/phantom': 'mod',
    '/editor': 'mod',
}


def resolve_home_tab(path: str) -> str:
    if path.startswith('/downloads/'):
        return 'download'
    return PATH_HOME_TAB.get(path, 'aux')


def normalize_home_tab(tab: str | None) -> str:
    if tab in VALID_HOME_TABS:
        return tab
    return 'aux'