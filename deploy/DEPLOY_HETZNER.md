# Перенос VerbaShake на Hetzner VPS

Что получится: приложение на своём домене с HTTPS (например `https://verbashake.app`),
не «засыпает», 4+ ГБ памяти. Streamlit Cloud работает как раньше, пока новый сервер
не проверен — переключение без простоя.

Файлы в проекте, которые для этого подготовлены:

| Файл | Что делает |
|---|---|
| `Dockerfile` | собирает приложение (Python 3.11, ffmpeg, CPU-версия torch) |
| `docker-compose.yml` | запускает приложение + Caddy (HTTPS) |
| `deploy/Caddyfile` | домен, сертификат, `/.well-known/` для будущего Google Play |
| `deploy/deploy.sh` | одна команда: загрузить код с Мака на сервер и перезапустить |
| `deploy/well-known/` | сюда позже положить `assetlinks.json` для TWA |

---

## Шаг 1. Купить домен (≈ €10–20 в год) — делаете вы

Любой регистратор: Cloudflare Registrar, Porkbun, Namecheap. Примеры: `verbashake.app`,
`verbashake.com`. Пока больше ничего не настраивайте — IP сервера будет на шаге 3.

## Шаг 2. SSH-ключ на Маке (если ещё нет) — 1 минута

```bash
ls ~/.ssh/id_ed25519.pub || ssh-keygen -t ed25519
```

Скопировать содержимое ключа (понадобится в Hetzner):

```bash
pbcopy < ~/.ssh/id_ed25519.pub
```

## Шаг 3. Создать сервер в Hetzner — делаете вы (оплата)

1. Регистрация на hetzner.com/cloud (нужна карта и проверка личности).
2. **Add Server**:
   - Location: Falkenstein / Nuremberg / Helsinki (ЕС, удобно для GDPR).
   - Image: **Ubuntu 24.04**.
   - Type: вкладка **Cost-Optimized**, **CX23** (x86, 4 ГБ RAM) для старта; при нехватке
     памяти сервер можно увеличить до **CX33** (8 ГБ). Не Regular Performance — он в разы дороже.
     (Whisper + MiniLM + torch вместе занимают ~1.5–2 ГБ.)
   - SSH keys: вставить ключ из шага 2.
   - Backups: включить (+20% к цене) — ежедневные снимки всего сервера.
3. Записать **IP-адрес** сервера.

## Шаг 4. DNS — делаете вы, у регистратора домена

Две записи типа **A**, обе указывают на IP сервера:

| Тип | Имя | Значение |
|---|---|---|
| A | `@` | IP сервера |
| A | `www` | IP сервера |

Обновление занимает от минут до пары часов.

## Шаг 5. Подготовить сервер — одна команда (могу выполнить я)

```bash
ssh root@<IP> 'curl -fsSL https://get.docker.com | sh && ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw allow 443/udp && ufw --force enable && mkdir -p /opt/verbashake/.streamlit'
```

## Шаг 6. Секреты и домен на сервере

Серверу нужен свой `secrets.toml` — в нём другой `redirect_uri` (локальный остаётся
для разработки на `localhost`).

```bash
scp .streamlit/secrets.toml root@<IP>:/opt/verbashake/.streamlit/secrets.toml
```

Затем на сервере поменять одну строку в секции `[auth]`:

```toml
redirect_uri = "https://<ваш-домен>/oauth2callback"
```

И указать домен для Caddy:

```bash
ssh root@<IP> 'echo DOMAIN=<ваш-домен> > /opt/verbashake/.env'
```

Ссылка возврата из Stripe Checkout берётся из этого же `redirect_uri`
(`app.py::_app_url`) — в Stripe ничего менять не нужно.

## Шаг 7. Google OAuth — делаете вы

console.cloud.google.com → APIs & Services → Credentials → ваш OAuth-клиент →
**Authorized redirect URIs** → добавить (старые не удалять):

```
https://<ваш-домен>/oauth2callback
```

## Шаг 8. Первый деплой

```bash
deploy/deploy.sh root@<IP>
```

Первая сборка ~5–10 минут (torch и остальные пакеты). При первом открытии
приложение скачает модели Whisper и MiniLM — они сохраняются в Docker-томе и
при следующих деплоях не скачиваются заново.

Логи:

```bash
ssh root@<IP> 'cd /opt/verbashake && docker compose logs -f app'
```

## Шаг 9. Проверка

- `https://<ваш-домен>` открывается, замок в адресной строке.
- Вход через Google → возврат в приложение.
- Урок с распознаванием речи (Whisper), озвучка, Premium-функция с Gemini.
- Установка как PWA (иконка в адресной строке Chrome).

## Шаг 10. Переключение

Когда всё работает — дать ученикам новую ссылку. Streamlit Cloud можно оставить
ещё на время как запасной или выключить в его панели.

---

## Обновления в дальнейшем

После изменений в коде:

```bash
deploy/deploy.sh root@<IP>
```

Раз в месяц — обновления системы:

```bash
ssh root@<IP> 'apt update && apt upgrade -y'
```

## Что остаётся как было

- **База данных** — Supabase (тот же `DATABASE_URL`). Бесплатный проект Supabase
  ставится на паузу после 7 дней без запросов; при живых учениках это не случится.
- **Stripe, Gemini, Google Sheets** — без изменений.
