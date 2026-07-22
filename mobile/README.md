# SkladPro — демо Android APK (WebView)

Минимальная нативная обёртка: WebView открывает сайт SkladPro. Обрабатывает
Back, offline/ошибки сети (экран с «Повторить»), splash-экран, иконку, загрузку
файлов (аватар), переживает поворот экрана.

## Почему WebView (а не Capacitor / TWA)
- **TWA** требует, чтобы сайт был PWA (manifest + service worker + HTTPS-домен +
  Digital Asset Links). Сейчас сайт — серверный SPA без PWA и без HTTPS-домена → блокер.
- **Capacitor** тянет Node-цепочку и всё равно грузит удалённый URL (backend live).
- **WebView** — ноль внешних зависимостей (даже без androidx), полный контроль над
  Back/offline/ошибками. Оптимально для «демо, открывающего мой сайт».

## Адрес сайта
`app/src/main/res/values/strings.xml` → `app_url`:
- `http://10.0.2.2:8000/` — dev-сервер на хосте из **эмулятора** (значение по умолчанию);
- для реального устройства/продакшена: `https://ваш-домен/`.

## Сборка (одна команда)
Нужны: JDK 17 и Android SDK (platform android-36, build-tools 36.0.0).
`local.properties` уже указывает на SDK.

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
