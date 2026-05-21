"""Catalog 数据查询封装。

search: 统一走 Q(name__icontains) | Q(description__icontains) 子串匹配
    （mysql + sqlite 一致，行为可预期；不再用 FULLTEXT，见用户反馈）。

tags__contains 在 sqlite 也不支持，所以 tag 过滤也做 sqlite fallback：
先用 ORM 取全部，再 Python 层 AND 过滤，最后手动分页。
"""
from django.db import connection
from django.db.models import Q

from skillshub.submit.models import Skill

PAGE_SIZE = 20

SORT_OPTIONS = {
    "newest": "-created_at",
    "updated": "-latest_version__published_at",
    "installs": "-install_count",
}
DEFAULT_SORT = "installs"


def list_skills(q: str = "", tags: list = None, sort: str = DEFAULT_SORT, page: int = 1):
    """返回 (skills_list, has_next)。

    仅展示 latest_version_id IS NOT NULL 的 skill (即至少有 published 版本)。

    Args:
        q: 搜索关键词
        tags: 多选 tag 列表 (AND 关系)
        sort: SORT_OPTIONS 之一
        page: 1-based 页号
    """
    if tags is None:
        tags = []

    qs = Skill.objects.filter(latest_version__isnull=False, is_listed=True)

    if q:
        # 子串匹配（name / description），行为可预期：搜 "api" 命中 "api-mock-server"。
        # 不用 MySQL FULLTEXT（ngram + natural language 对短词/子串语义反直觉，见
        # 用户反馈）；企业内几千行小表 LIKE 全表扫描仍是亚毫秒级。migration 0004 的
        # FULLTEXT 索引留着不用，无害。
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))

    order = SORT_OPTIONS.get(sort, SORT_OPTIONS[DEFAULT_SORT])
    qs = qs.order_by(order)

    if tags:
        if connection.vendor == "mysql":
            for tag in tags:
                qs = qs.filter(tags__contains=[tag])
            start = (page - 1) * PAGE_SIZE
            end = page * PAGE_SIZE
            items = list(qs[start : end + 1])
        else:
            # sqlite: tags__contains 不支持，Python 层 AND 过滤
            all_items = list(qs)
            for tag in tags:
                all_items = [s for s in all_items if tag in (s.tags or [])]
            start = (page - 1) * PAGE_SIZE
            end = page * PAGE_SIZE
            items = all_items[start : end + 1]
    else:
        start = (page - 1) * PAGE_SIZE
        end = page * PAGE_SIZE
        items = list(qs[start : end + 1])

    has_next = len(items) > PAGE_SIZE
    return items[:PAGE_SIZE], has_next
