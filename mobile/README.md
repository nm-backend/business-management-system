# SkladPro — демо Android APK (WebView)

> **Какой проект основной.** В `mobile/` два Android-проекта:
> - **`mobile/app` (Java) — основной.** Именно он включён в корневую сборку
>   (`mobile/settings.gradle` → `include ':app'`); команды ниже относятся к нему.
> - **`mobile/android-demo/` (Kotlin) — отдельный standalone-проект** со своим
>   `settings.gradle`, в корневую сборку НЕ входит. Это параллельный вариант
>   той же WebView-обёртки (другие имя строкового ресурса — `site_url`, язык
>   строк и детали); собирается только из своей папки. Если сомневаетесь,
>   работайте с `mobile/app`.

Минимальная нативная обёртка: WebView открывает сайт SkladPro. Обрабатывает
Back, offline/ошибки сети (экран с «Повторить»), splash-экран, иконку, загрузку
файлов (аватар), переживает поворот экрана.

## Почему WebView (а не Capacitor / TWA)
- **TWA** требует полноценного PWA (manifest + service worker + HTTPS-домен +
  Digital Asset Links + installability-критерии). У сайта PWA-заготовка ЕСТЬ:
  `static/manifest.json` и `static/sw.js` (кэш + уведомления, scope `/`),
  но нет HTTPS-домена и Digital Asset Links, а installability-критерии
  (маскируемые PNG-иконки 192/512, push-обработчик) не закрыты → блокер.
- **Capacitor** тянет Node-цепочку и всё равно грузит удалённый URL (backend live).
- **WebView** — ноль внешних зависимостей (даже без androidx), полный контроль над
  Back/offline/ошибками. Оптимально для «демо, открывающего мой сайт».

## Адрес сайта
`app/src/main/res/values/strings.xml` → `app_url`:
- `http://10.0.2.2:8000/` — dev-сервер на хосте из **эмулятора** (значение по умолчанию);
- для реального устройства/продакшена: `https://ваш-домен/`.

## Сборка (одна команда)
Нужны: JDK 17 и Android SDK (platform android-36, build-tools 36.0.0).
Создайте `mobile/local.properties` с путём к SDK (файл локальный, в репозитории
его нет):
```properties
sdk.dir=/path/to/Android/Sdk
```

```bash
# из папки mobile/
gradle assembleDebug          # → app/build/outputs/apk/debug/app-debug.apk
gradle assembleRelease        # → app/build/outputs/apk/release/app-release-unsigned.apk
```

Готовый debug-APK ставится на устройство/эмулятор:
```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## Требования среды
| Компонент | Версия |
|---|---|
| JDK | 17 |
| Android Gradle Plugin | 8.7.2 |
| Gradle | 8.9 |
| compileSdk / build-tools | 36 / 36.0.0 |
| minSdk / targetSdk | 26 / 34 |

Release-подпись: сгенерируйте keystore и настройте `signingConfigs` перед публикацией
(для демо достаточно `assembleDebug`).
