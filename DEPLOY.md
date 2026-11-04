# Correr el bot en un servidor (sin depender de tu compu)

## Opción 0: GitHub Actions (gratis, sin tarjeta; respaldo cada 10 minutos)

GitHub corre `python arbitraje.py --ciclo` cada 10 minutos en sus servidores: una pasada
de escaneo, responde los comandos de Telegram que llegaron desde la corrida anterior,
y termina. El estado (`cooldown.json` y el umbral cambiado con `/umbral`) se guarda en
el cache de Actions entre corridas.

Lo que cambia respecto a correrlo en tu compu:
- Las alertas y las respuestas a comandos llegan con hasta 10 a 15 minutos de demora
  (GitHub suele atrasar un poco los cron).
- El repositorio es público (el código, no el token: ese va en un secreto del repo).

Dónde está todo:
- Repositorio: https://github.com/ulisesbob/bot-arbitraje
- Corridas y logs: pestaña Actions del repo. "Run workflow" lo dispara a mano.
- Secretos: Settings > Secrets and variables > Actions (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).

Para actualizar el bot después de cambiar código, desde la carpeta `cripto-arbitraje`:

```bash
git add -A
```

```bash
git commit -m "lo que cambiaste"
```

```bash
git push
```

Para pausarlo: Actions > bot arbitraje > "..." > Disable workflow. Para volver a correrlo
en tu compu, deshabilitá el workflow primero: dos bots leyendo el mismo chat se pisan.

## Alertas cada minuto: reloj en Cloudflare Workers (gratis, sin tarjeta)

GitHub Actions no puede correr más seguido que cada 10 o 15 minutos. Para escanear cada
minuto, un Worker de Cloudflare ([cloudflare/worker.js](cloudflare/worker.js)) con un cron
`* * * * *` llama a `POST /api/scan` en Vercel ([api/scan.py](api/scan.py)), que hace la
pasada completa (arbitraje simple + rulos) y devuelve el estado actualizado. El Worker guarda
ese estado en Cloudflare KV y lo manda en la próxima llamada. Toda la lógica sigue en Python.

Configurar (una vez):

1. Crear cuenta gratuita en https://dash.cloudflare.com/sign-up (solo email).
2. Loguear la herramienta (abre el navegador):

```bash
cd "C:\Users\Ulise\Desktop\strat qqq 38%\cripto-arbitraje\cloudflare"; npx wrangler login
```

3. Correr el script, que redespliega Vercel, crea el namespace KV, carga el secreto y despliega el Worker:

```bash
cd "C:\Users\Ulise\Desktop\strat qqq 38%\cripto-arbitraje"; powershell -ExecutionPolicy Bypass -File deploy\cloudflare_setup.ps1
```

4. Deshabilitar el workflow de GitHub Actions (si no, los dos escanean con estados
   separados y las alertas llegan duplicadas): Actions > bot arbitraje > ... > Disable workflow.

Ver que está vivo: https://bot-arbitraje-reloj.ulisesarbitrajebot.workers.dev/ultimo muestra la
última corrida guardada, cuánto tardó y cuántas alertas mandó (se guarda cuando algo cambia o
cada 10 minutos, así que la hora puede tener hasta 10 minutos de atraso). Logs en vivo:
`npx wrangler tail` desde la carpeta `cloudflare`. Panel: https://dash.cloudflare.com >
Workers & Pages > bot-arbitraje-reloj.

Límites del plan gratuito que importan: 100.000 ejecuciones por día (usamos 1.440) y 1.000
escrituras de KV por día (el Worker escribe solo cuando el estado cambia o cada 10 minutos).

Para actualizar después de cambiar código: `vercel --prod --yes` (la lógica está en Vercel);
el Worker solo cambia si tocás `cloudflare/worker.js`, y entonces `npx wrangler deploy`.

## Comandos al instante: webhook en Vercel (gratis, sin tarjeta; activo)

GitHub Actions solo corre cada 10 minutos, demasiado lento para contestar un `/dolar`.
Por eso los comandos los atiende una función en Vercel ([api/telegram.py](api/telegram.py)):
Telegram le manda cada mensaje por webhook y responde en alrededor de 1 segundo.
GitHub Actions sigue haciendo solo las alertas (`--ciclo --sin-comandos`).

Dónde está todo:
- Proyecto: https://vercel.com/ulisesbobs-projects/bot-arbitraje
- URL del webhook: https://bot-arbitraje-xi.vercel.app/api/telegram (un GET muestra la
  versión desplegada y huellas de la configuración, sin exponer valores).
- Variables: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `WEBHOOK_SECRET` (en Settings >
  Environment Variables). El secreto también está en tu `config.json` local como `webhook_secret`.

Para actualizar después de cambiar código (el push a GitHub NO redespliega Vercel solo):

```bash
vercel --prod --yes
```

Para configurar desde cero en otra máquina: `deploy/vercel_setup.ps1` carga las variables y
despliega; después hay que registrar el webhook en Telegram con `setWebhook` (URL de arriba
y `secret_token` igual a `webhook_secret`).

Limitaciones de Vercel: no puede escribir archivos, así que `/umbral N` no guarda el cambio;
el umbral se cambia en `CONFIG_DEFAULT` de `arbitraje.py` y se sube con push (para Actions)
y `vercel --prod --yes` (para los comandos).

Si alguna vez querés volver a leer mensajes desde Actions o desde tu compu, primero hay que
borrar el webhook (`deleteWebhook`), porque mientras exista Telegram no entrega mensajes por
`getUpdates`.

## Otras opciones (siempre prendido, alertas al minuto)

Tres caminos, del más rápido al más barato. En todos, antes de arrancar apagá el bot
local (Ctrl-C en la pestaña) para que no haya dos bots leyendo el mismo chat de
Telegram: si corren dos a la vez, se reparten los comandos y uno responde y el otro no.

Cuesta lo mismo en todos los casos: casi nada de CPU y menos de 100 MB de RAM.

## Opción A: Railway (ya tenés el CLI instalado)

Costo: el plan Hobby son US$ 5 por mes e incluye US$ 5 de uso. Este bot consume
alrededor de US$ 1 a 2 por mes, así que entra en lo incluido. Hay un período de prueba
con crédito limitado y sin tarjeta.

1. Iniciá sesión (abre el navegador):

```bash
railway login
```

2. Desde la carpeta `cripto-arbitraje`, creá el proyecto y subilo:

```bash
railway init --name bot-arbitraje
```

```bash
railway up --detach
```

3. Cargá las credenciales (el token y el chat id de tu `config.json`):

```bash
railway variables --set TELEGRAM_BOT_TOKEN=xxx --set TELEGRAM_CHAT_ID=yyy
```

4. Ver que corre:

```bash
railway logs
```

Para actualizar el bot después de cambiar código, de nuevo `railway up --detach`.

## Opción B: un VPS Linux, Oracle Cloud Free Tier o una Raspberry Pi

Costo: Oracle Free Tier es gratis para siempre (pide tarjeta para verificar identidad pero
no cobra). Cualquier VPS chico de DigitalOcean, Hetzner, Contabo o similar cuesta
US$ 4 a 6 por mes. Una Raspberry Pi en tu casa cuesta la electricidad.

Necesitás: una máquina con Ubuntu o Debian y acceso por SSH.

1. Copiá la carpeta entera al servidor (con `config.json` ya cargado):

```bash
scp -r "C:\Users\Ulise\Desktop\strat qqq 38%\cripto-arbitraje" usuario@IP_DEL_SERVIDOR:~/
```

2. Entrá y corré el instalador:

```bash
ssh usuario@IP_DEL_SERVIDOR
```

```bash
sudo bash ~/cripto-arbitraje/deploy/instalar_servidor.sh
```

El script instala Python, copia el bot a `/opt/bot-arbitraje`, crea un servicio de
sistema que arranca solo al prender la máquina y se reinicia si se cae.

Comandos útiles después:

```bash
journalctl -u bot-arbitraje -f
```

```bash
sudo systemctl restart bot-arbitraje
```

## Opción C: Fly.io

Costo: similar a Railway, alrededor de US$ 2 por mes para esta máquina. Pide tarjeta.

1. Instalá el CLI desde https://fly.io/docs/flyctl/install/ y hacé `fly auth login`.
2. Desde la carpeta `cripto-arbitraje`:

```bash
fly launch --no-deploy --copy-config
```

```bash
fly secrets set TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy
```

```bash
fly deploy
```

```bash
fly logs
```

## Cómo funciona la configuración en el servidor

El `Dockerfile` (Railway y Fly) no copia `config.json`: el token y el chat id van por
variables de entorno y el resto usa los valores por defecto del código. `/umbral` sigue
funcionando y guarda el cambio, pero se pierde si el contenedor se reinicia. Si querés
otro umbral permanente, cambiá `umbral_pct` en `CONFIG_DEFAULT` dentro de `arbitraje.py`
antes de subir.

En la opción B sí se copia tu `config.json` tal cual, con todo lo que tengas ahí.

## Probar la imagen Docker en tu compu (opcional)

```bash
docker build -t bot-arbitraje .
```

```bash
docker run --rm -e TELEGRAM_BOT_TOKEN=xxx -e TELEGRAM_CHAT_ID=yyy bot-arbitraje
```
