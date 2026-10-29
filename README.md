# FlowPilot — приватний конструктор інтеграцій (MVP)

Початкова самостійна вебплатформа: один власник, логін, сценарії Webhook → HTTP (POST/PUT/PATCH), JSON-мапінг, тестові запуски, статуси, історія, SQLite.

## Запуск через Docker

1. `cp .env.example .env`
2. В `.env` встановіть довгі випадкові `APP_SECRET` та `ADMIN_PASSWORD`. Наприклад, згенеруйте їх через `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'` (двічі).
3. `mkdir -p data && chmod 777 data` (для локальної демоверсії; для сервера краще `chown 10001:10001 data`).
4. `docker compose up --build -d`
5. Відкрийте `http://localhost:8000`, увійдіть як `admin` з паролем з `.env`.

Сервіс навмисно слухає лише `127.0.0.1`. Для публічного приймання webhooks налаштуйте HTTPS reverse proxy із захистом, доменом, `PUBLIC_BASE_URL=https://ваш-домен` і `COOKIE_SECURE=true`.

## Перший сценарій

1. «Новий сценарій» → вкажіть HTTPS URL API-отримувача, метод, заголовки та JSON-шаблон тіла.
2. Наприклад: `{"name":"{{payload.name}}","email":"{{payload.email}}"}`.
3. Збережіть; скопіюйте персональний webhook URL.
4. Приклад: `curl -X POST 'http://localhost:8000/hook/ВАШ_ТОКЕН' -H 'Content-Type: application/json' -d '{"name":"Olena","email":"olena@example.com"}'`.
5. Перегляньте історію; можна також виконати тест прямо на сторінці сценарію.

## Схема

`External service → POST /hook/<secret> → validation / JSON field mapping → outbound HTTPS request → SQLite run log`

## Межі MVP та безпека

- Це **не повний паритет** з ApiX-Drive: поки немає OAuth-конекторів, drag-and-drop canvas, тригерів розкладу, черги задач, retry, версіонування, умов/гілок і багатокрокових сценаріїв.
- Працює лише з HTTPS-отримувачами через стандартні HTTP запити. API ключі зберігаються у SQLite як текст; не використовуйте цю версію для чутливих production-секретів без шифрованого сховища.
- На login немає rate limit/MFA. Не відкривайте програму напряму в інтернет; потрібен reverse proxy із rate limit, HTTPS і контроль доступу.
- URL перевіряється на приватні IP і забороняє redirects, проте DNS rebinding між перевіркою і виконанням теоретично можливий. Для production потрібен egress firewall та DNS-pinned HTTP client.
- Вебхуки виконуються синхронно. Для великих навантажень використовуйте фонову чергу і робітники.
- При зміні ADMIN_PASSWORD у `.env` вже створений hash у БД не зміниться. Для скидання у цьому MVP потрібно створити нову БД (з втратою сценаріїв) або розширити функцію зміни пароля.
- Резервуйте папку `data/`; ніколи не комітьте `.env` та `data/` в git.
