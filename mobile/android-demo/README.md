# SkladPro — демо-APK (Android WebView)

Нативная Android-обёртка, открывающая сайт SkladPro. Выбрана WebView (а не
Capacitor/TWA): полный контроль над Back/offline/ошибками сети, минимум
зависимостей (только JDK + Android SDK, без Node), весь проект — в этой папке.

## Что уже готово (в репозитории)
- Полный Gradle-проект (`settings.gradle`, `build.gradle`, `app/build.gradle`).
- `MainActivity.kt` — WebView с:
  - загрузкой сайта (URL в `app/src/main/res/values/strings.xml` → `site_url`);
  - JavaScript + DOM storage (localStorage для JWT — иначе вход не работает);
  - обработкой системной **Back** (навигация внутри WebView, затем выход);
  - экраном **offline / ошибки сети** с кнопкой «Повторить»;
  - **pull-to-refresh**;
  - выбором файла для загрузки фото/аватара (`<input type=file>`);
  - отклонением **SSL-ошибок** (не игнорируем, безопасность).
- **Иконка** приложения (adaptive, векторная — без бинарных PNG).
- **Splash screen** (тема `Theme.SkladPro.Splash`).
- **Название** приложения — `SkladPro` (`strings.xml`).
- **Release-конфигурация без debug** (`debuggable false`, отдельная подпись).
- `network_security_config.xml`, `keystore.properties.example`, `.gitignore`.

## Чего НЕ хватает в текущей среде (доказано проверкой)
Собрать APK здесь **невозможно** — отсутствуют обязательные компоненты:

| Компонент | Проверка | Статус |
|---|---|---|
| **JDK 17** (`java`, `javac`) | `java -version` → `command not found` | ❌ отсутствует |
| **Android SDK** (`sdkmanager`, `platform-tools`, `platforms;android-34`, `build-tools;34.0.0`) | `ANDROID_HOME` пусто, нет `sdkmanager`/`adb` | ❌ отсутствует |
| Gradle 8.7 | нет в PATH | ❌ (даёт Android Studio или wrapper) |
| Node/npm | v24 / v11 | ✅ (для WebView не нужен) |

Без JDK и Android SDK не существует `android.jar`, `aapt2`, `d8` — компилировать
и паковать APK нечем. Это относится к ЛЮБОМУ способу (WebView/Capacitor/TWA).

## Сборка APK (после установки JDK + Android SDK)

### Шаг 0. Прописать адрес сайта
В `app/src/main/res/values/strings.xml` → `site_url`:
- продакшен: `https://ваш-домен`
- эмулятор: `http://10.0.2.2:8000`
- телефон в одной сети: `http://IP-компьютера:8000`

### Вариант A — Android Studio (проще всего; ставит JDK+SDK+Gradle сам)
1. Открыть папку `mobile/android-demo` в Android Studio.
2. Дождаться Gradle sync.
3. **Debug-APK одной кнопкой:** Build → Build APK(s) → `app/build/outputs/apk/debug/app-debug.apk`.

### Вариант B — командная строка
Требуется JDK 17, Android SDK (API 34, build-tools 34.0.0), Gradle 8.7.
```bash
# один раз сгенерировать wrapper (если нет gradlew):
gradle wrapper --gradle-version 8.7

# ДЕМО-APK (debug-подпись, ставится сразу) — ОДНА КОМАНДА:
./gradlew assembleDebug
# → app/build/outputs/apk/debug/app-debug.apk
```

### Release-APK без debug (для показа/раздачи)
1. Создать ключ (один раз):
   ```bash
   keytool -genkeypair -v -keystore skladpro-demo.keystore \
       -alias skladpro -keyalg RSA -keysize 2048 -validity 10000
   ```
2. `cp keystore.properties.example keystore.properties` и заполнить пароли.
3. ```bash
   ./gradlew assembleRelease
   # → app/build/outputs/apk/release/app-release.apk (подписан, debuggable=false)
   ```

## Проверка на устройстве
```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```
Сначала поднимите backend (`docker compose up`), чтобы `site_url` отвечал.
