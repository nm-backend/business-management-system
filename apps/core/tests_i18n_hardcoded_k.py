"""
Страж локализации: во фронтенд-коде не должно быть пользовательских текстов.

Требование ТЗ: «Все тексты интерфейса должны храниться в отдельных файлах
локализации. Нельзя писать текст прямо в коде.» Правило периодически
нарушалось (панель долгов, лента кассы, вкладки уведомлений, карточка
материала, квартальный отчёт), поэтому проверяем его автоматически.

Комментарии (они на русском по всему проекту — это документация кода, а не
интерфейс) вырезаются лексером, проверяется только исполняемый код и строковые
литералы.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

CYRILLIC_RUN = re.compile(r'[А-Яа-яЁёЎўҚқҒғҲҳІіЇїЄєҢңӨөҮүЈј]{3,}')

# Единственное законное исключение: названия языков в переключателе пишутся
# на самом языке и не переводятся (Ўзбекча остаётся Ўзбекча в русском UI).
ALLOWED = {'Ўзбекча', 'Русский', 'Кыргызча', 'Ozbekcha'}


def strip_comments(source: str) -> str:
    """
    Убирает // и /* */ комментарии, не трогая содержимое строк.

    Мини-лексер со стеком контекстов: обычные строки, шаблонные литералы
    (включая вложенные ${...} с новыми шаблонами внутри) и regex-литералы
    (.replace(/"/g, ...)). Без этого кавычка внутри регулярки или вложенный
    шаблон «съезжали», и остаток файла разбирался неверно — комментарии
    попадали в отчёт как «текст интерфейса».
    """
    REGEX_PREFIX = set('(,=:[!&|?;{}+-*%^~')
    out = []
    i, n = 0, len(source)
    # Контексты: ('code', braces) | ('str', quote) | ('tpl', None)
    stack = [['code', 0]]
    prev_significant = ''

    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ''
        kind = stack[-1][0]

        if kind == 'str':
            out.append(ch)
            if ch == '\\':
                if i + 1 < n:
                    out.append(nxt)
                i += 2
                continue
            if ch == stack[-1][1]:
                stack.pop()
            i += 1
            continue

        if kind == 'tpl':
            if ch == '\\':
                out.append(ch)
                if i + 1 < n:
                    out.append(nxt)
                i += 2
                continue
            if ch == '`':
                out.append(ch)
                stack.pop()
                i += 1
                continue
            if ch == '$' and nxt == '{':
                out.append('${')
                stack.append(['code', 0])
                i += 2
                continue
            out.append(ch)
            i += 1
            continue

        # ── code ────────────────────────────────────────────────────────────
        if ch == '/' and nxt == '/':
            while i < n and source[i] != '\n':
                i += 1
            continue
        if ch == '/' and nxt == '*':
            i += 2
            while i + 1 < n and not (source[i] == '*' and source[i + 1] == '/'):
                if source[i] == '\n':
                    out.append('\n')  # сохраняем нумерацию строк
                i += 1
            i += 2
            continue
        if ch in ('"', "'"):
            stack.append(['str', ch])
            out.append(ch)
            prev_significant = ch
            i += 1
            continue
        if ch == '`':
            stack.append(['tpl', None])
            out.append(ch)
            prev_significant = ch
            i += 1
            continue
        if ch == '/' and (prev_significant in REGEX_PREFIX or prev_significant == ''):
            i += 1
            in_class = False
            while i < n:
                c = source[i]
                if c == '\\':
                    i += 2
                    continue
                if c == '[':
                    in_class = True
                elif c == ']':
                    in_class = False
                elif c == '/' and not in_class:
                    i += 1
                    break
                elif c == '\n':
                    break
                i += 1
            out.append(' ')
            prev_significant = '/'
            continue
        if ch == '{':
            stack[-1][1] += 1
        elif ch == '}':
            if stack[-1][1] == 0 and len(stack) > 1:
                stack.pop()  # конец ${...} — возвращаемся в шаблон
                out.append(ch)
                i += 1
                continue
            stack[-1][1] = max(0, stack[-1][1] - 1)
        out.append(ch)
        if not ch.isspace():
            prev_significant = ch
        i += 1
    return ''.join(out)


def _blank_keep_lines(match):
    """Заменяет комментарий пустотой, сохраняя переводы строк (нумерация)."""
    return '\n' * match.group(0).count('\n')


def strip_html_comments(source: str) -> str:
    """Убирает <!-- --> и {# #} — это документация разметки, а не интерфейс."""
    source = re.sub(r'<!--.*?-->', _blank_keep_lines, source, flags=re.S)
    source = re.sub(r'{#.*?#}', _blank_keep_lines, source, flags=re.S)
    source = re.sub(r'{%\s*comment\s*%}.*?{%\s*endcomment\s*%}', _blank_keep_lines, source, flags=re.S)
    return source



class NoHardcodedUiTextTests(SimpleTestCase):
    def _js_files(self):
        root = Path(settings.BASE_DIR) / 'static' / 'js'
        for path in sorted(root.rglob('*.js')):
            if 'vendor' in path.parts:
                continue
            yield path

    def test_no_cyrillic_ui_text_in_js(self):
        offenders = []
        for path in self._js_files():
            # HTML-комментарии внутри шаблонных строк — тоже документация кода.
            code = strip_html_comments(strip_comments(path.read_text(encoding='utf-8')))
            for line_no, line in enumerate(code.splitlines(), start=1):
                for match in CYRILLIC_RUN.findall(line):
                    if match in ALLOWED:
                        continue
                    offenders.append(
                        f'{path.relative_to(settings.BASE_DIR)}:{line_no} — «{match}»'
                    )
        self.assertFalse(
            offenders,
            'Текст интерфейса зашит в коде вместо locale/*.json:\n  '
            + '\n  '.join(offenders),
        )

    def test_no_cyrillic_ui_text_in_templates(self):
        """В шаблонах допустим только текст с data-i18n (он перезаписывается)."""
        root = Path(settings.BASE_DIR) / 'templates'
        offenders = []
        for path in sorted(root.rglob('*.html')):
            if 'admin' in path.parts:
                continue  # переопределения Django-админки — интерфейс суперадмина
            text = strip_html_comments(path.read_text(encoding='utf-8'))
            # Внутри <script> действуют правила JS: комментарии там — тоже
            # документация кода, а не интерфейс.
            text = re.sub(
                r'(<script\b[^>]*>)(.*?)(</script>)',
                lambda m: m.group(1) + strip_comments(m.group(2)) + m.group(3),
                text, flags=re.S,
            )
            for line_no, line in enumerate(text.splitlines(), 1):
                if 'data-i18n' in line or '{% trans' in line or '{{' in line:
                    continue
                for match in CYRILLIC_RUN.findall(line):
                    if match in ALLOWED:
                        continue
                    offenders.append(f'{path.relative_to(settings.BASE_DIR)}:{line_no} — «{match}»')
        self.assertFalse(
            offenders,
            'Текст интерфейса зашит в шаблоне вместо locale/*.json:\n  '
            + '\n  '.join(offenders),
        )


class NoHardcodedNotificationTextTests(SimpleTestCase):
    """
    Тексты уведомлений тоже интерфейс: они должны приходить из locale/*.json
    на языке получателя, а не строкой из кода.

    Раньше бизнес-события уведомляли всегда по-узбекски, а события подписки —
    всегда по-русски, независимо от языка пользователя.
    """

    # Функции, чьи текстовые аргументы попадают пользователю на экран.
    USER_FACING_CALLS = {'notify', 'notify_staff', 'send_push_to_user', '_notify_owner'}

    def test_notification_calls_use_locale_keys(self):
        import ast

        root = Path(settings.BASE_DIR) / 'apps'
        offenders = []
        for path in sorted(root.rglob('*.py')):
            if 'tests' in path.name or 'migrations' in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = getattr(func, 'id', None) or getattr(func, 'attr', None)
                if name not in self.USER_FACING_CALLS:
                    continue
                # Определение самой функции пропускаем — там нет литералов.
                values = list(node.args) + [kw.value for kw in node.keywords]
                for value in values:
                    literals = []
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        literals.append(value.value)
                    elif isinstance(value, ast.JoinedStr):  # f-строка
                        literals += [
                            part.value for part in value.values
                            if isinstance(part, ast.Constant) and isinstance(part.value, str)
                        ]
                    for literal in literals:
                        for match in CYRILLIC_RUN.findall(literal):
                            offenders.append(
                                f'{path.relative_to(settings.BASE_DIR)}:{value.lineno} '
                                f'— {name}(… «{match}» …)'
                            )
        self.assertFalse(
            offenders,
            'Текст уведомления зашит в коде — используйте title_key/message_key '
            'или core.utils.translate(key, user.language):\n  ' + '\n  '.join(offenders),
        )


class NoHardcodedReportTextTests(SimpleTestCase):
    """
    Отчёты и экспорты (PDF/Excel/CSV) — тоже пользовательский текст.

    Шапки таблиц и заголовки отчётов должны приходить из locale/*.json на
    языке владельца/администратора, а не из строк в apps/reports.
    """

    def test_report_module_has_no_ui_literals(self):
        import ast

        root = Path(settings.BASE_DIR) / 'apps' / 'reports'
        offenders = []
        for path in sorted(root.glob('*.py')):
            # apps.py/admin.py/models.py — подписи Django-админки (интерфейс
            # суперадмина, он русскоязычный), проверяем слой отчётов.
            if path.name.startswith('tests') or path.name in {'apps.py', 'admin.py', 'models.py'}:
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            # Докстринги — документация, не интерфейс: собираем их, чтобы пропустить.
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(node, clean=False)
                    if doc:
                        docstrings.add(doc)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                if node.value in docstrings:
                    continue
                for match in CYRILLIC_RUN.findall(node.value):
                    offenders.append(
                        f'{path.relative_to(settings.BASE_DIR)}:{node.lineno} — «{match}»'
                    )
        self.assertFalse(
            offenders,
            'Текст отчёта зашит в коде вместо locale/*.json '
            '(используйте core.utils.translate(key, user.language)):\n  '
            + '\n  '.join(offenders),
        )
