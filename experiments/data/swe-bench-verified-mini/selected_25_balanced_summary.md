# SWE-bench Verified Mini 25 条均衡子集

选择原则：从 50 条中选 25 条；尽量保持 `django/django` 与 `sphinx-doc/sphinx` 均衡，覆盖不同功能区域，并保持 medium/hard 难度比例接近原始集合。

说明：正式实验子集排除了已经用于调试链路的 `django__django-11790`、`django__django-11880`、`django__django-9296`，避免调试过程影响正式结果。

## 分布

### Repo

| 类别 | 数量 |
| --- | ---: |
| `django/django` | 13 |
| `sphinx-doc/sphinx` | 12 |

### Difficulty

| 类别 | 数量 |
| --- | ---: |
| `hard` | 8 |
| `medium` | 17 |

### Area

| 类别 | 数量 |
| --- | ---: |
| `django:admin` | 2 |
| `django:contrib` | 1 |
| `django:db/models/migrations` | 5 |
| `django:forms` | 2 |
| `django:other` | 2 |
| `django:utils` | 1 |
| `sphinx:builders` | 2 |
| `sphinx:domains` | 2 |
| `sphinx:ext` | 3 |
| `sphinx:other` | 3 |
| `sphinx:util` | 2 |

## 推荐清单

| # | Instance | Repo | Area | Difficulty | Patch len | Files | FAIL_TO_PASS | First file |
| ---: | --- | --- | --- | --- | ---: | ---: | ---: | --- |
| 1 | `django__django-12308` | `django/django` | `django:admin` | `medium` | 684 | 1 | 2 | `django/contrib/admin/utils.py` |
| 2 | `django__django-12713` | `django/django` | `django:admin` | `hard` | 1986 | 1 | 1 | `django/contrib/admin/options.py` |
| 3 | `django__django-12155` | `django/django` | `django:contrib` | `hard` | 2268 | 2 | 1 | `django/contrib/admindocs/utils.py` |
| 4 | `django__django-12304` | `django/django` | `django:db/models/migrations` | `medium` | 510 | 1 | 1 | `django/db/models/enums.py` |
| 5 | `django__django-12209` | `django/django` | `django:db/models/migrations` | `medium` | 464 | 1 | 1 | `django/db/models/base.py` |
| 6 | `django__django-11815` | `django/django` | `django:db/models/migrations` | `medium` | 739 | 1 | 2 | `django/db/migrations/serializer.py` |
| 7 | `django__django-11964` | `django/django` | `django:db/models/migrations` | `medium` | 559 | 1 | 2 | `django/db/models/enums.py` |
| 8 | `django__django-12406` | `django/django` | `django:db/models/migrations` | `hard` | 2165 | 2 | 3 | `django/db/models/fields/related.py` |
| 9 | `django__django-12193` | `django/django` | `django:forms` | `medium` | 525 | 1 | 1 | `django/forms/widgets.py` |
| 10 | `django__django-12276` | `django/django` | `django:forms` | `medium` | 839 | 1 | 2 | `django/forms/widgets.py` |
| 11 | `django__django-12262` | `django/django` | `django:other` | `medium` | 680 | 1 | 4 | `django/template/library.py` |
| 12 | `django__django-12039` | `django/django` | `django:other` | `medium` | 1268 | 1 | 1 | `django/db/backends/ddl_references.py` |
| 13 | `django__django-11848` | `django/django` | `django:utils` | `medium` | 869 | 1 | 2 | `django/utils/http.py` |
| 14 | `sphinx-doc__sphinx-8269` | `sphinx-doc/sphinx` | `sphinx:builders` | `medium` | 594 | 1 | 1 | `sphinx/builders/linkcheck.py` |
| 15 | `sphinx-doc__sphinx-7985` | `sphinx-doc/sphinx` | `sphinx:builders` | `hard` | 1472 | 1 | 2 | `sphinx/builders/linkcheck.py` |
| 16 | `sphinx-doc__sphinx-9698` | `sphinx-doc/sphinx` | `sphinx:domains` | `medium` | 638 | 1 | 1 | `sphinx/domains/python.py` |
| 17 | `sphinx-doc__sphinx-8551` | `sphinx-doc/sphinx` | `sphinx:domains` | `hard` | 1205 | 2 | 1 | `sphinx/domains/python.py` |
| 18 | `sphinx-doc__sphinx-8721` | `sphinx-doc/sphinx` | `sphinx:ext` | `medium` | 573 | 1 | 1 | `sphinx/ext/viewcode.py` |
| 19 | `sphinx-doc__sphinx-8056` | `sphinx-doc/sphinx` | `sphinx:ext` | `hard` | 1878 | 1 | 1 | `sphinx/ext/napoleon/docstring.py` |
| 20 | `sphinx-doc__sphinx-8548` | `sphinx-doc/sphinx` | `sphinx:ext` | `hard` | 3907 | 2 | 1 | `sphinx/ext/autodoc/__init__.py` |
| 21 | `sphinx-doc__sphinx-9367` | `sphinx-doc/sphinx` | `sphinx:other` | `medium` | 759 | 1 | 1 | `sphinx/pycode/ast.py` |
| 22 | `sphinx-doc__sphinx-10323` | `sphinx-doc/sphinx` | `sphinx:other` | `medium` | 728 | 1 | 1 | `sphinx/directives/code.py` |
| 23 | `sphinx-doc__sphinx-11510` | `sphinx-doc/sphinx` | `sphinx:other` | `hard` | 2867 | 1 | 2 | `sphinx/directives/other.py` |
| 24 | `sphinx-doc__sphinx-9230` | `sphinx-doc/sphinx` | `sphinx:util` | `medium` | 533 | 1 | 1 | `sphinx/util/docfields.py` |
| 25 | `sphinx-doc__sphinx-7757` | `sphinx-doc/sphinx` | `sphinx:util` | `medium` | 1738 | 1 | 1 | `sphinx/util/inspect.py` |

## 使用方式

批量实验时优先读取：

```text
experiments/data/swe-bench-verified-mini/selected_25_balanced.jsonl
```

如果需要只传 instance id，则使用：

```text
experiments/data/swe-bench-verified-mini/selected_25_balanced_ids.txt
```
