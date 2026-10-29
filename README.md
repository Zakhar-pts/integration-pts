# PTS Cooperation Integration v3 — Personal Lead Routing

## Що працює
- Приватний кабінет з логіном; оригінальний логотип PTS Cooperation (`static/pts-cooperation-original.png`, з наданого зображення).
- Створення сценарію з Webhook URL, тестовий JSON, журнал статусів, увімкнення/вимкнення.
- **Багато приймачів для одного джерела:** основна дія плюс додаткові Telegram/TG Bot, Google Sheets, HTTP/CRM, Gmail, OpenAI та Facebook Page.
- Приймання ADSQuiz, форм сайту та інших квізів через POST JSON на секретний webhook.
- Meta Lead Ads webhook: підтвердження `GET /meta/webhook`, підпис HMAC SHA-256 для POST, отримання lead data через Graph API, передавання у сценарії з `source=meta`. Потрібні токен сторінки, дозволи, Meta App і підписка на `leadgen`. Не тестовано з реальним Meta.
- Токени сервісів зберігаються шифровано (Fernet); паролі не зберігаються в Git.

## Обмеження
Це **робочий MVP, а не 1:1 реалізація всього ApiX-Drive**. Немає готового OAuth login для Google/Meta, автоматичного refresh-токенів, планувальника, гарантованих retry/queue, idempotency для лідів, редагування додаткового приймача (видалити й додати заново), UI-мапінгу кожного поля, Instagram/Google Ads Lead Ads конекторів. Не перевірено з реальними зовнішніми обліковими записами. Facebook Lead Ads вимагає Meta App review і коректних permissions. Кнопка тесту надсилає реальні запити зовнішнім API.

## Оновлення існуючого GitHub/Render
1. Збережи стару версію і дані (якщо вони є). Нові таблиці створюються без міграції існуючих структур. Перед оновленням на реальному PostgreSQL зроби backup.
2. Розпакуй ZIP. **Завантаж в корінь `integration-pts` усі файли, папки `templates/` і `static/` з їхніми шляхами**. На GitHub браузерне завантаження вкладених файлів може потребувати drag-and-drop папок або git push.
3. НЕ завантажуй `.env`, токени, SQLite базу, `__pycache__` чи `.pyc`.
4. Render → Environment: `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `APP_SECRET`, `ENCRYPTION_KEY`, `COOKIE_SECURE=true`, `DATABASE_URL` (або використовуй SQLite значення за замовчуванням `/app/data/flowpilot.db`, але сховище Render Free тимчасове).
5. Generate Fernet key locally: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. ЗБЕРЕЖИ ключ у менеджері секретів: зміна ключа зробить старі токени недоступними.
6. Для Meta: `META_VERIFY_TOKEN`, `META_APP_SECRET`, `META_PAGE_ACCESS_TOKEN` в Environment. HTTPS webhook `https://YOUR-SERVICE.onrender.com/meta/webhook`. У Meta потрібно налаштувати leadgen webhook та permissions. У новому сценарії вибрати джерело Facebook Lead Ads. Для інших форм використовуй /hook/TOKEN.
7. Перевір статус Live, `/health`, кабінет, тест з **фіктивними** даними. Для Google Sheets/Gmail потрібен чинний OAuth access token з відповідними scopes і оновлення після закінчення строку дії вручну.

## Рекомендації для production
Render Free засинає, тому не гарантує своєчасне приймання лідів; SQLite ephemeral. Потрібні постійна БД, завжди активний сервер, черга + retry + idempotency, секретне сховище, бекапи, моніторинг, журнал без PII, перевірка SSRF/DNS rebinding. Не приймай реальні персональні дані клієнтів до захисту та перевірки конфігурації.

## Docker local
`cp .env.example .env`, налаштуй секрети, `docker compose up --build`. Веб-адреса залежить від docker-compose.yml.
